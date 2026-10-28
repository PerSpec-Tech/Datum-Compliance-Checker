"""BCF 2.1 export: one topic per failing result, so IFC users can open the issues in their
own tool (Solibri, BIMcollab, Archicad, BlenderBIM…). Standard library only.

Zip layout:  bcf.version · project.bcfp · <topic guid>/markup.bcf · <topic guid>/viewpoint.bcfv
The viewpoint selects the element by its IfcGuid (= source_id) when the model came from IFC.
"""

from __future__ import annotations

import io
import uuid
import zipfile
from typing import Any
from xml.etree import ElementTree as ET

NS_TOPIC = uuid.UUID("6f4a3c1e-0b52-4f5c-9a77-2d8e1b0c4a11")  # stable topic ids per report + result


def _xml(root: ET.Element) -> bytes:
    ET.indent(root)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _sub(parent: ET.Element, tag: str, text: str | None = None, **attrs: str) -> ET.Element:
    el = ET.SubElement(parent, tag, attrs)
    if text is not None:
        el.text = text
    return el


def export(report: dict[str, Any], *, source_kind: str, project_name: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        version = ET.Element("Version", VersionId="2.1")
        _sub(version, "DetailedVersion", "2.1")
        z.writestr("bcf.version", _xml(version))

        project = ET.Element("ProjectExtension")
        _sub(project, "Project", ProjectId=str(uuid.uuid5(NS_TOPIC, report["project_id"])))
        _sub(project.find("Project"), "Name", project_name)
        z.writestr("project.bcfp", _xml(project))

        for r in report["results"]:
            if r["status"] != "fail":
                continue
            element = r["element"] or {}
            guid = str(uuid.uuid5(NS_TOPIC, f"{report['id']}:{r['rule_id']}:{element.get('id')}"))
            markup = ET.Element("Markup")
            topic = _sub(markup, "Topic", Guid=guid, TopicType="Issue", TopicStatus="Open")
            _sub(
                topic,
                "Title",
                f"{r['title']}" + (f" ({element['id']})" if element.get("id") else ""),
            )
            _sub(
                topic,
                "Priority",
                {"critical": "Critical", "major": "Major", "minor": "Minor"}[r["severity"]],
            )
            _sub(topic, "CreationDate", report["created_at"])
            _sub(topic, "CreationAuthor", "Compliance Checker")
            lines = [r["message"]]
            if r["fix_by"]:
                f = r["fix_by"]
                unit = f" {f['unit']}" if f["unit"] else ""
                lines.append(f"Fix: {f['direction']} by {f['amount']:g}{unit}")
            lines.append(
                f'Clause {r["clause"]["ref"]} — {r["clause"]["source"]}: "{r["clause"]["excerpt"]}"'
            )
            if r["rule_status"] == "draft":
                lines.append("Rule status: draft (not yet verified by a person).")
            _sub(topic, "Description", "\n".join(lines))
            _sub(topic, "Labels", r["rule_id"])
            vp_guid = str(uuid.uuid5(NS_TOPIC, guid + ":vp"))
            vps = _sub(markup, "Viewpoints", Guid=vp_guid)
            _sub(vps, "Viewpoint", "viewpoint.bcfv")
            z.writestr(f"{guid}/markup.bcf", _xml(markup))

            vis = ET.Element("VisualizationInfo", Guid=vp_guid)
            components = _sub(vis, "Components")
            if source_kind == "ifc" and element.get("source_id"):
                selection = _sub(components, "Selection")
                _sub(selection, "Component", IfcGuid=element["source_id"])
            _sub(components, "Visibility", DefaultVisibility="true")
            z.writestr(f"{guid}/viewpoint.bcfv", _xml(vis))
    return buf.getvalue()
