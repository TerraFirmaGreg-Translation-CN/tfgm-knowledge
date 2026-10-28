import json
from pathlib import Path
import time
from .ragflow import Client
from .ingest import save


def retrieve(config,report,question):
    if not report.get('ready'):raise ValueError('知识包尚未解析完成，不能当作可用数据集')
    client=Client.configured(config)
    data,_=client.call('POST','/retrieval',{'dataset_ids':[report['dataset_id']],'question':question,'page_size':5,'similarity_threshold':0.1,'vector_similarity_weight':0.7,'keyword':False})
    mapping={d['document_id']:d for d in report['documents'].values()}
    results=[]
    media_dir=Path(report['media_directory']) if report.get('media_directory') else None
    media=json.loads((media_dir/'media.json').read_text()) if media_dir else None
    for chunk in data.get('chunks',[]):
        document=mapping.get(chunk.get('document_id'))
        if not document:raise ValueError('检索结果来自知识包之外的文档')
        results.append({'title':document['title'],'source_url':document['source_url'],'content':chunk['content'],'score':chunk.get('similarity'),'document_id':chunk['document_id']})
        if media is not None:
            from .media import image_reference
            relation=document.get('media',{})
            results[-1]['images']=[image_reference(x,media,media_dir) for x in relation.get('images',[])]
            results[-1]['structures']=[media['structures'][x['id']] for x in relation.get('structures',[])]
            results[-1]['recipes']=[{**media['recipes'][rid], 'image':image_reference(media['recipes'][rid]['image'],media,media_dir) if media['recipes'][rid].get('image') else None} for rid in relation.get('recipes',[])]
            results[-1]['unresolved_recipes']=relation.get('unresolved_recipes',[])
    return results


def evaluate(config,report_path,cases_path,output):
    report=json.loads(Path(report_path).read_text());cases=json.loads(Path(cases_path).read_text());rows=[]
    for case in cases:
        begin=time.monotonic();results=retrieve(config,report,case['question'])
        relevant=[r for r in results if r['title'] in case['expected_titles']]
        hit=any(any(term in r['content'] for term in case['evidence_terms']) for r in relevant)
        rows.append({**case,'hit_at_5':hit,'seconds':round(time.monotonic()-begin,2),'results':results})
        print(('✓ ' if hit else '✗ ')+case['question'],flush=True)
    result={'package_id':report['package_id'],'profile':report['profile'],'documents':report['expected_documents'],'chunks':report['chunk_count'],'embedding_model':report['embedding_model'],'method':'hybrid vector=0.7, top5, no reranker, source-title + evidence-term check','hits':sum(x['hit_at_5'] for x in rows),'total':len(rows),'cases':rows,'limitation':'8 个预览覆盖范围内的人工 smoke cases；不是全量问答准确率，也未评估最终生成答案'}
    out=Path(output);save(out.with_suffix('.json'),result)
    text=[f"# {result['package_id']} 检索预览验收",f"\n范围：{result['documents']} 篇文档，{result['chunks']} 个分块。",f"\n模型：{result['embedding_model']}；Top-5 证据命中：{result['hits']}/{result['total']}。",'\n'+result['limitation']]
    for row in rows:
        text += ['\n## '+row['question'],'\n结果：'+('命中' if row['hit_at_5'] else '未命中')+f"；耗时 {row['seconds']} 秒。"]
        for r in row['results'][:3]:
            text += [f"\n- [{r['title']}]({r['source_url']})（{r['score']:.3f}）",'\n> '+r['content'][:360].replace('\n','\n> ')]
    out.with_suffix('.md').write_text('\n'.join(text)+'\n')
    return result
