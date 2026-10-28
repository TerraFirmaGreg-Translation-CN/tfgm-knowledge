"""Read FTB's relaxed SNBT without executing upstream code.

Supports omitted commas, comments, typed arrays, numeric suffixes and quoted
strings. Rejects trailing content, duplicate keys and excessive nesting.
"""

import re


class ParseError(ValueError):
    pass


class Parser:
    def __init__(self, text):
        self.text = text
        self.pos = 0

    def error(self, message):
        line = self.text.count("\n", 0, self.pos) + 1
        raise ParseError(f"{message} at line {line}, offset {self.pos}")

    def space(self):
        while self.pos < len(self.text):
            if self.text[self.pos].isspace():
                self.pos += 1
            elif self.text.startswith("//", self.pos) or self.text[self.pos] == "#":
                end = self.text.find("\n", self.pos)
                self.pos = len(self.text) if end < 0 else end + 1
            elif self.text.startswith("/*", self.pos):
                end = self.text.find("*/", self.pos + 2)
                if end < 0:
                    self.error("Unclosed comment")
                self.pos = end + 2
            else:
                break

    def take(self, character):
        self.space()
        if self.text.startswith(character, self.pos):
            self.pos += len(character)
            return True
        return False

    def string(self):
        quote = self.text[self.pos]
        self.pos += 1
        out = []
        escapes = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f"}
        while self.pos < len(self.text):
            c = self.text[self.pos]
            self.pos += 1
            if c == quote:
                return "".join(out)
            if c == "\\":
                if self.pos == len(self.text):
                    self.error("Unclosed escape")
                c = self.text[self.pos]
                self.pos += 1
                if c == "u":
                    raw = self.text[self.pos:self.pos + 4]
                    if not re.fullmatch(r"[0-9a-fA-F]{4}", raw):
                        self.error("Invalid unicode escape")
                    c = chr(int(raw, 16))
                    self.pos += 4
                elif c in escapes:
                    c = escapes[c]
                elif c not in ("\\", "\"", "'"):
                    # Preserve unknown game-specific escapes verbatim.
                    c = "\\" + c
            out.append(c)
        self.error("Unclosed string")

    def value(self, depth=0):
        if depth > 100:
            self.error("Nesting limit exceeded")
        self.space()
        if self.pos >= len(self.text):
            self.error("Expected value")
        if self.text[self.pos] in ("\"", "'"):
            return self.string()
        if self.take("{"):
            result = {}
            while not self.take("}"):
                self.space()
                if self.pos >= len(self.text):
                    self.error("Unclosed compound")
                if self.text[self.pos] in ("\"", "'"):
                    key = self.string()
                else:
                    match = re.match(r"[^\s:{}\[\],]+", self.text[self.pos:])
                    if not match:
                        self.error("Expected key")
                    key = match[0]
                    self.pos += len(key)
                if key in result:
                    self.error(f"Duplicate key {key}")
                if not self.take(":"):
                    self.error("Expected colon")
                result[key] = self.value(depth + 1)
                self.take(",")
            return result
        if self.take("["):
            self.space()
            typed = re.match(r"[BILbil]\s*;", self.text[self.pos:])
            if typed:
                self.pos += len(typed[0])
            result = []
            while not self.take("]"):
                result.append(self.value(depth + 1))
                self.take(",")
            return result
        match = re.match(r"[^\s,\[\]{}]+", self.text[self.pos:])
        if not match:
            self.error("Expected scalar")
        token = match[0]
        self.pos += len(token)
        if token.lower() in ("true", "false"):
            return token.lower() == "true"
        if re.fullmatch(r"[+-]?\d+[bBsSlL]?", token):
            return int(token.rstrip("bBsSlL"))
        if re.fullmatch(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?[fFdD]?", token):
            return float(token.rstrip("fFdD"))
        return token


def loads(text):
    parser = Parser(text)
    result = parser.value()
    parser.space()
    if parser.pos != len(text):
        parser.error("Trailing content")
    return result
