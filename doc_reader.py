# -*- coding: utf-8 -*-
"""
文档内容提取：基于开源库 markitdown（微软），支持 PDF / Word(doc/docx) /
PPT(ppt/pptx) / Excel(xls/xlsx/csv) / HTML / Markdown / TXT / JSON / 图片OCR 等。
"""
import os

from markitdown import MarkItDown

_md = None

# 送给大模型做摘要前的原文长度上限：
# 云端模型上下文大，可多给；本地4B模型只有8k上下文，必须压得更小
MAX_CHARS_CLOUD = 30000
MAX_CHARS_LOCAL = 6000


def _get_markitdown():
    global _md
    if _md is None:
        _md = MarkItDown()
    return _md


def _looks_valid_binary(file_path):
    """
    markitdown 对损坏的二进制文档会降级为"按纯文本读取"，垃圾内容也会被提取出来。
    这里按扩展名校验文件头魔数，提前拦掉伪造/损坏的 Office、PDF 文件。
    """
    ext = os.path.splitext(file_path)[1].lower().lstrip(".")
    with open(file_path, "rb") as fp:
        head = fp.read(8)
    if ext in ("docx", "docm", "dotx", "pptx", "pptm", "potx", "xlsx", "xlsm", "xltx"):
        return head.startswith(b"PK\x03\x04")  # 新Office本质是zip
    if ext in ("doc", "ppt", "xls"):
        return head.startswith(b"\xd0\xcf\x11\xe0")  # 旧版OLE复合文档
    if ext == "pdf":
        return head.startswith(b"%PDF")
    return True


def _is_garbage_text(text):
    """乱码兜底：可打印文本中不应出现大量控制字符"""
    sample = text[:5000]
    if not sample:
        return True
    bad = sum(1 for ch in sample if ord(ch) < 32 and ch not in "\n\r\t")
    return bad / len(sample) > 0.05


def extract_text(file_path):
    """
    提取文档纯文本（markitdown 会自动按文件类型选择解析器）。
    :return: 文本字符串；解析失败/内容为空/文件损坏时返回 ""
    """
    if not _looks_valid_binary(file_path):
        print(f"[doc_reader] 文件头与扩展名不符，疑似损坏: {os.path.basename(file_path)}")
        return ""
    try:
        result = _get_markitdown().convert(file_path)
    except Exception as e:
        print(f"[doc_reader] 解析失败 {os.path.basename(file_path)}: {e}")
        return ""
    text = (result.text_content or "").strip()
    if _is_garbage_text(text):
        return ""
    # 压缩连续空白行，去掉无意义的空转
    lines = [line.rstrip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line.strip())


def truncate_for_model(text, use_local=False):
    """按当前对话模式的上下文容量截断原文，超长时注明"""
    limit = MAX_CHARS_LOCAL if use_local else MAX_CHARS_CLOUD
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n……（文档过长，已截取前{limit}字）"
