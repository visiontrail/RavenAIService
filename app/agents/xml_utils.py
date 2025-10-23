"""
XML utilities for structured tool outputs and agent messages.
Mimics Claude-style tags for document and metadata structuring.
"""
from typing import Any, Dict, List, Optional
from xml.etree.ElementTree import Element, SubElement, tostring


def _set_attrs(el: Element, attrs: Optional[Dict[str, Any]] = None):
    if attrs:
        for k, v in attrs.items():
            el.set(str(k), str(v))


def element_to_string(el: Element) -> str:
    return tostring(el, encoding="unicode")


def xml_tag(tag: str, text: Optional[str] = None, attrs: Optional[Dict[str, Any]] = None, children: Optional[List[Element]] = None) -> str:
    root = Element(tag)
    _set_attrs(root, attrs)
    if text is not None:
        root.text = text
    if children:
        for c in children:
            root.append(c)
    return element_to_string(root)


def dict_to_xml(tag: str, data: Dict[str, Any], attrs: Optional[Dict[str, Any]] = None) -> str:
    root = Element(tag)
    _set_attrs(root, attrs)
    for k, v in data.items():
        child = SubElement(root, str(k))
        child.text = str(v)
    return element_to_string(root)


def wrap_document(content: str, meta: Optional[Dict[str, Any]] = None, tag: str = "document") -> str:
    root = Element(tag)
    if meta:
        meta_el = SubElement(root, "meta")
        for k, v in meta.items():
            child = SubElement(meta_el, str(k))
            child.text = str(v)
    body_el = SubElement(root, "content")
    body_el.text = content
    return element_to_string(root)


def wrap_metadata(metadata: Dict[str, Any]) -> str:
    return dict_to_xml("log_metadata", metadata)


def wrap_file_list(files: List[Dict[str, Any]], source: Optional[str] = None) -> str:
    pkg = Element("log_package")
    if source:
        pkg.set("source", source)
    fl = SubElement(pkg, "file_list")
    for f in files:
        item = SubElement(fl, "file")
        for k, v in f.items():
            if k == "path":
                item.set("path", str(v))
            else:
                sub = SubElement(item, str(k))
                sub.text = str(v)
    return element_to_string(pkg)


def wrap_excerpt(path: str, start_line: int, end_line: int, snippet: str, match: Optional[str] = None) -> str:
    ex = Element("excerpt")
    ex.set("path", path)
    ex.set("start_line", str(start_line))
    ex.set("end_line", str(end_line))
    if match:
        ex.set("match", match)
    body = SubElement(ex, "text")
    body.text = snippet
    return element_to_string(ex)


def wrap_search_results(query: str, results: List[Dict[str, Any]]) -> str:
    sr = Element("search_results")
    sr.set("query", query)
    for r in results:
        item = SubElement(sr, "result")
        for k, v in r.items():
            if k in {"path", "score"}:
                item.set(k, str(v))
            else:
                sub = SubElement(item, str(k))
                sub.text = str(v)
    return element_to_string(sr)


def wrap_plan(steps: List[str]) -> str:
    plan = Element("plan")
    for i, s in enumerate(steps, start=1):
        step = SubElement(plan, "step")
        step.set("id", str(i))
        step.text = s
    return element_to_string(plan)