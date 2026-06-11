"""Selftest fuer runtime/persona/cubase_plugin_sync.py.

Testet:
- XML-Parser (VST3 + VST2) gegen die echten Cubase-XMLs des Hosts.
- Diff-Logik: to_add / to_update / to_remove / unchanged.
- Merge preserviert handgepflegte Felder (vendor/type/version/tags via plugin_tags.json).
- Backup-File wird bei apply=True angelegt (gegen tmpdir).

Aufruf:
    python -m tests.selftests.cubase_plugin_sync_selftest
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.persona.cubase_plugin_sync import (  # noqa: E402
    XmlPluginEntry,
    apply_diff,
    compute_diff,
    default_xml_paths,
    parse_vst2_xml,
    parse_vst3_xml,
    sync,
)


def test_default_paths_resolve() -> None:
    paths = default_xml_paths()
    assert "vst3" in paths and "vst2" in paths
    assert paths["vst3"].name == "VstPlugInfoV4.xml"
    assert paths["vst2"].name == "Vst2xPlugin Infos Cubase.xml"


def test_parse_vst3_xml_host() -> None:
    p = default_xml_paths()["vst3"]
    if not p.exists():
        print(f"  SKIP test_parse_vst3_xml_host — {p} fehlt")
        return
    entries = parse_vst3_xml(p)
    assert len(entries) > 100, f"erwartet >100 VST3-Plugins, gefunden {len(entries)}"
    omni = [e for e in entries if e.uid == "84E8DE5F9255222296FAE4133C935A18"]
    assert len(omni) == 1
    assert omni[0].name == "Omnisphere"
    assert omni[0].out_bus == 9
    assert omni[0].flags == 13
    assert omni[0].vst_format == "VST3"


def test_parse_vst2_xml_host() -> None:
    p = default_xml_paths()["vst2"]
    if not p.exists():
        print(f"  SKIP test_parse_vst2_xml_host — {p} fehlt")
        return
    entries = parse_vst2_xml(p)
    assert len(entries) > 5, f"erwartet >5 VST2-Plugins, gefunden {len(entries)}"
    glasgow = [e for e in entries if e.name == "Glasgow"]
    if glasgow:
        assert glasgow[0].vendor == "KORG"
        assert glasgow[0].sub_category == "Instrument"
        assert glasgow[0].vst_format == "VST2"


def test_compute_diff_preserves_hand_curated() -> None:
    registry = {
        "plugins": [
            {
                "name": "FabFilter Pro-Q 3",
                "vendor": "FabFilter",
                "type": "Fx|EQ",
                "version": "3.24.0",
                "vst_format": "VST3",
            },
        ],
    }
    xml = [XmlPluginEntry(
        uid="AABBCCDD11223344AABBCCDD11223344",
        name="FabFilter Pro-Q 3",
        vst_format="VST3",
        in_bus=1, out_bus=1, in_arr=3, out_arr=3,
        latency=0, sidechain_bus=1, flags=25,
    )]
    diff = compute_diff(registry, xml, [])
    assert len(diff.to_add) == 0
    assert len(diff.to_update) == 1
    upd = diff.to_update[0]
    assert upd["match"] == "name_backfill"
    assert "uid" in upd["changes"]
    assert "cubase_tech" in upd["changes"]

    merged = apply_diff(registry, diff)
    pro_q = next(p for p in merged["plugins"] if p["name"] == "FabFilter Pro-Q 3")
    # Hand-curated bleibt
    assert pro_q["vendor"] == "FabFilter"
    assert pro_q["type"] == "Fx|EQ"
    assert pro_q["version"] == "3.24.0"
    # XML-Felder kommen dazu
    assert pro_q["uid"] == "AABBCCDD11223344AABBCCDD11223344"
    assert pro_q["cubase_tech"]["sidechain_bus"] == 1
    assert pro_q["cubase_tech"]["flags"] == 25


def test_compute_diff_detects_add_and_remove() -> None:
    registry = {
        "plugins": [
            {"name": "Old Plugin", "uid": "OLDUID00000000000000000000000000", "vst_format": "VST3"},
        ],
    }
    xml = [XmlPluginEntry(
        uid="NEWUID00000000000000000000000000",
        name="Shiny New Plugin",
        vst_format="VST3",
        in_bus=1, out_bus=1,
    )]
    diff = compute_diff(registry, xml, [])
    assert len(diff.to_add) == 1
    assert diff.to_add[0]["name"] == "Shiny New Plugin"
    assert len(diff.to_remove) == 1
    assert diff.to_remove[0]["name"] == "Old Plugin"


def test_apply_remove_stale_flag() -> None:
    registry = {"plugins": [{"name": "Stale", "uid": "STALEUID", "vst_format": "VST3"}]}
    diff = compute_diff(registry, [], [])
    merged_keep = apply_diff(registry, diff, remove_stale=False)
    assert len(merged_keep["plugins"]) == 1
    merged_drop = apply_diff(registry, diff, remove_stale=True)
    assert len(merged_drop["plugins"]) == 0


def test_sync_dry_run_does_not_write(tmp_path: Path | None = None) -> None:
    tmp = Path(tempfile.mkdtemp())
    reg = tmp / "yoka_plugins.json"
    reg.write_text(json.dumps({"plugins": []}), encoding="utf-8")
    res = sync(apply=False, registry_path=reg)
    assert res["applied"] is False
    assert res["backup"] is None
    # Datei unveraendert (immer noch leere plugins-Liste)
    after = json.loads(reg.read_text(encoding="utf-8"))
    assert after == {"plugins": []}


def test_sync_apply_creates_backup() -> None:
    tmp = Path(tempfile.mkdtemp())
    reg = tmp / "yoka_plugins.json"
    reg.write_text(json.dumps({
        "plugins": [{"name": "Existing", "vendor": "Acme", "vst_format": "VST3"}],
    }), encoding="utf-8")
    # Leere XMLs -> Diff = nur to_remove
    fake_xml3 = tmp / "v3.xml"
    fake_xml3.write_text('<?xml version="1.0"?><VstPlugInfo></VstPlugInfo>', encoding="utf-8")
    fake_xml2 = tmp / "v2.xml"
    fake_xml2.write_text('<?xml version="1.0"?><Vst2xPlugins></Vst2xPlugins>', encoding="utf-8")
    res = sync(apply=True, registry_path=reg,
               xml_paths={"vst3": fake_xml3, "vst2": fake_xml2})
    assert res["applied"] is True
    assert res["backup"] is not None
    assert Path(res["backup"]).exists()


def main() -> int:
    tests = [
        test_default_paths_resolve,
        test_parse_vst3_xml_host,
        test_parse_vst2_xml_host,
        test_compute_diff_preserves_hand_curated,
        test_compute_diff_detects_add_and_remove,
        test_apply_remove_stale_flag,
        test_sync_dry_run_does_not_write,
        test_sync_apply_creates_backup,
    ]
    fails = 0
    for t in tests:
        try:
            t()
            print(f"  PASS {t.__name__}")
        except AssertionError as e:
            print(f"  FAIL {t.__name__}: {e}")
            fails += 1
        except Exception as e:  # noqa: BLE001
            print(f"  ERROR {t.__name__}: {type(e).__name__}: {e}")
            fails += 1
    print(f"\n{'OK' if fails == 0 else 'FAIL'} — {len(tests) - fails}/{len(tests)} passed")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
