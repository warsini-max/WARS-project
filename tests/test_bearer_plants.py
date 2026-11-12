"""Bearer plants are PPE (PSAK 216 ¶3(b), ¶6, ¶22A, ¶37(i); option A, Gail 12 Nov 2026 11.59).

Each rule has a positive test and a negative test (rule 7). Lines are synthetic, built from the layouts of
non-case development reports (ASII 2022, KMTR 2022, PTBA 2022, PSDN 2022); no PDF is stored."""
from types import SimpleNamespace as NS

from wars_scanner import check
from wars_scanner import pdf_reader as PR
from wars_scanner import xbrl_pipeline as XP
from wars_scanner.pdf_reader import Value
from wars_scanner.text import Msg, keys_in


def L(text, page=75):
    return [(page, ln, set(XP.X._amounts(ln)) - {None}) for ln in text.strip("\n").split("\n")]


# ASII 2022 note 14 (billions): the carrying line is mature + immature (7,310 = 5,675 + 1,635)
ASII = """
14. TANAMAN PRODUKTIF 14. BEARER PLANTS
Pada awal Penambahan/ Pengurangan/ Reklasifikasi/ Pada akhir
Harga perolehan Acquisition cost
Tanaman menghasilkan 8,857 - (41) 596 9,412 Mature plantations
Tanaman belum menghasilkan 1,614 617 - (596) 1,635 Immature plantations
10,471 617 (41) - 11,047
Akumulasi penyusutan Accumulated depreciation
Tanaman menghasilkan (3,357) (421) 41 - (3,737) Mature plantations
Nilai tercatat 7,114 7,310 Carrying value
"""
PAGES = {"bs": [13], "pl": [15]}


def test_bearer_movement_anchored_on_mature_plus_immature():
    assert XP.BEARER_CONCEPTS == ("PlantationAssetsMature", "PlantationAssetsImmature")
    got = XP.movement_charge(L(ASII), 7_310, PAGES)
    assert got is not None and got[0] == 421 and got[1] == 75
    # must NOT read: anchored on the mature figure alone (5,675 is not the table's carrying line)
    assert XP.movement_charge(L(ASII), 5_675, PAGES) is None


def test_bearer_plants_not_a_non_ppe_class():
    # option A replaces rule 4 for bearer plants only; mining properties and concession rights stay non-PPE
    assert "PlantationAssetsMature" not in XP.NON_PPE_CONCEPTS
    assert {"MiningProperties", "TollRoadConcessionRights", "InvestmentProperties"} <= set(XP.NON_PPE_CONCEPTS)


def test_bearer_face_labels_positive_and_negative():
    yes = ["Tanaman produktif - neto", "Tanaman produktif, setelah dikurangi", "Tanaman perkebunan",
           "Tanaman menghasilkan", "Tanaman belum menghasilkan", "Tanaman telah menghasilkan"]
    for s in yes:
        assert PR.BEARER_FACE.search(PR._norm(s)), s
    assert PR.BEARER_TOTAL.search(PR._norm("Jumlah tanaman produktif"))
    # must NOT match: biological assets, timber plantations (PSAK 241 ¶5A(a)), annual crops, advances, plasma
    no = ["Aset biologis", "Tanaman industri", "Hutan tanaman industri", "Tanaman semusim",
          "Tanaman perkebunan semusim", "Uang muka pembelian tanaman produktif", "Piutang plasma",
          "Aset tetap", "Tanaman produktif industri"]
    for s in no:
        n = PR._norm(s)
        assert not PR.BEARER_FACE.search(n) and not PR.BEARER_TOTAL.search(n), s


def _line(label, t=None, t1=None, page=4):
    am = {k: v for k, v in (("t", t), ("t1", t1)) if v is not None}
    return NS(label=label, full_label=label, amounts=am, page=page, text=label, quote="")


def _vals(ppe_t=1_114, ppe_t1=1_141, dep=(91, 99)):
    return [Value("property_plant_equipment_net", "t", ppe_t, "FOUND", [4]),
            Value("property_plant_equipment_net", "t1", ppe_t1, "FOUND", [4]),
            Value("ppe_depreciation_disclosed", "t", dep[0], "FOUND", [79]),
            Value("ppe_depreciation_disclosed", "t1", dep[1], "FOUND", [79])]


def test_pdf_path_adds_bearer_line_to_ppe():
    # KMTR 2022: a heading without amounts and the mature line with them
    pos = NS(lines=[_line("Tanaman perkebunan"), _line("Tanaman menghasilkan", 204, 219), _line("Aset tetap", 1_114, 1_141)])
    out = PR._add_bearer_plants(_vals(), pos, 2022)
    ppe = {v.column: v for v in out if v.field == "property_plant_equipment_net"}
    assert ppe["t"].value == 1_318 and ppe["t1"].value == 1_360
    assert ppe["t"].status == "REVIEW" and "note.ppe_plus_bearer" in keys_in(ppe["t"].note)
    dep = {v.column: v for v in out if v.field == "ppe_depreciation_disclosed"}
    assert dep["t"].value == 91 and dep["t"].status == "REVIEW" and "note.dep_bearer_missing" in keys_in(dep["t"].note)


def test_pdf_path_total_line_not_added_twice():
    pos = NS(lines=[_line("Tanaman menghasilkan", 150, 160), _line("Tanaman belum menghasilkan", 50, 40),
                    _line("Jumlah tanaman produktif", 200, 200), _line("Aset tetap", 1_000, 1_000)])
    out = PR._add_bearer_plants(_vals(1_000, 1_000), pos, 2022)
    ppe = {v.column: v.value for v in out if v.field == "property_plant_equipment_net"}
    assert ppe == {"t": 1_200, "t1": 1_200}


def test_pdf_path_bearer_label_without_amounts_asks_for_them():
    # PSDN / ASII: the label is wrapped and its amounts were not read: PPE stays as read, REVIEW, with a note
    pos = NS(lines=[_line("Tanaman produktif"), _line("Aset tetap - neto", 437, 447)])
    out = PR._add_bearer_plants(_vals(437, 447), pos, 2022)
    ppe = {v.column: v for v in out if v.field == "property_plant_equipment_net"}
    assert ppe["t1"].value == 447 and ppe["t1"].status == "REVIEW"
    assert "note.ppe_bearer_unread" in keys_in(ppe["t1"].note)


def test_pdf_path_no_bearer_line_changes_nothing():
    pos = NS(lines=[_line("Aset biologis", 5, 6), _line("Hutan tanaman industri", 7, 8), _line("Aset tetap", 1_000, 1_000)])
    out = PR._add_bearer_plants(_vals(1_000, 1_000), pos, 2022)
    assert all(v.status == "FOUND" and not v.note for v in out)
    assert {v.column: v.value for v in out if v.field == "property_plant_equipment_net"} == {"t": 1_000, "t1": 1_000}


def _r(fy=2022):
    return NS(inputs={"fiscal_year_t": fy})


def test_card_reasons_for_bearer_plants():
    R = check._reason
    assert R("property_plant_equipment_net", "bearer plants 7,310 included (PSAK 216)", [], _r())[0].key == "chk.r.ppe_bearer"
    assert R("ppe_depreciation_disclosed", "allocation table p78; bearer plants depreciation 421 (movement table p75)",
             [], _r())[0].key == "chk.r.dep_bearer"
    assert R("ppe_depreciation_disclosed", "PDF notes = allocation table; bearer plants on the face; their depreciation "
             "was not read", [], _r())[0].key == "chk.r.dep_bearer_missing"
    # PDF-only path: the notes are Indonesian catalogue text
    assert R("property_plant_equipment_net", str(Msg("note.ppe_bearer_unread", psak="PSAK 216")), [], _r())[0].key \
        == "chk.r.ppe_bearer_unread"
    assert R("ppe_depreciation_disclosed", str(Msg("note.dep_bearer_missing")), [], _r())[0].key == "chk.r.dep_bearer_missing"
    # must NOT: a PPE note without bearer plants
    assert R("property_plant_equipment_net", "single source", [], _r())[0].key == "chk.r.single"


def test_single_xbrl_movement_source_is_not_a_conflict():
    # KMTR, PTBA 2022: 'XBRL movement table only' used to give the conflict card with no figure ('—')
    R = check._reason
    assert R("ppe_depreciation_disclosed", "XBRL movement table only · not read from the PDF", [], _r())[0].key == "chk.r.single"
    # still a conflict when the XBRL movement gives a second figure
    got = R("ppe_depreciation_disclosed", "PDF notes · XBRL movement table gives 10,290,400,648", [], _r())[0]
    assert got.key == "chk.r.dep_conflict"


def test_depreciation_card_components_with_translation_difference():
    # ASII 2022: allocation total 10,920 less translation difference 571 (both printed) + bearer plants 421
    xr = NS(xbrl={"dep_bearer": {"t": (10_349, 421, 75, 78, (10_920, 571)), "t1": (10_541, 391, 75, 78, (10_585, 44))}},
            tax={}, pdf=None)
    parts = check._sum_parts(xr)["ppe_depreciation_disclosed"]
    assert [p[0].key for p in parts] == ["dep.cls.alloc", "dep.cls.fx", "dep.cls.bearer"]
    assert sum(p[1] for p in parts) == 10_770 and sum(p[2] for p in parts) == 10_932
    # PTBA 2022: the two years of the PPE figure on two pages
    xr = NS(xbrl={"dep_bearer": {"t": (1_429_971, 14_108, 94, 88, None), "t1": (1_110_881, 17_110, 94, 89, None)}},
            tax={}, pdf=None)
    parts = check._sum_parts(xr)["ppe_depreciation_disclosed"]
    assert parts[0][3] == "88, 89" and check._page_ints(parts[0][3]) == [88, 89]
    # must NOT name components when the PPE page is unknown in one year
    xr = NS(xbrl={"dep_bearer": {"t": (1, 2, 94, None, None), "t1": (1, 2, 94, 89, None)}}, tax={}, pdf=None)
    assert "ppe_depreciation_disclosed" not in check._sum_parts(xr)
