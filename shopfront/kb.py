"""GIVEN: generates Shopfront's knowledge base, data/kb/ (Node 07).

    python -m shopfront.kb            # rewrites data/kb/ (deterministic; the files are committed)

The KB is what a support or ops agent would search: the help center (copied from data/help_center), one page per
product (specs, care, warranty, customer questions), ARCHIVED pages for the 2024 and 2025 models of every product
(near-duplicates with stale specs: the classic retrieval trap), troubleshooting guides, buying guides, and a few ARCHIVED
articles whose facts conflict with current ones (status: archived). Every file has front matter with id, title,
type, status and updated. Product facts are derived from the catalog in the seeded database's product list below,
so they agree with what tools return: `build_kb` reads them from a freshly seeded database.
"""
from __future__ import annotations

import html
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELP = ROOT / "data" / "help_center"
KB = ROOT / "data" / "kb"


WARRANTY = {
    "kitchen": "1 year",
    "outdoor": "2 years, excluding wear and tear",
    "home-office": "5 years on the frame; 1 year on motors and electronics",
    "lighting": "2 years",
    "electronics-accessories": "1 year",
    "bags": "1 year",
}

# family -> (weight per size or fixed, materials, care, in the box, faq list)
FAMILIES: list[tuple[str, dict]] = [
    ("Cast Iron Skillet", {"warranty": "Lifetime on the iron", "weight": {"8 in": "1.6 kg", "10 in": "2.4 kg", "12 in": "3.5 kg"},
     "materials": "Cast iron, pre-seasoned with vegetable oil", "box": "Skillet, silicone handle sleeve",
     "care": "Hand-wash, dry immediately, wipe with a thin layer of oil. Never soak or put in the dishwasher.",
     "faq": [("Does it work on induction?", "Yes, on gas, induction, electric, in the oven and over a campfire."),
             ("It arrived with a sticky surface. Is it defective?", "No: that's excess seasoning oil. Heat it "
              "upside down in the oven at 230°C for an hour.")]}),
    ("Enameled Dutch Oven", {"warranty": "Lifetime on the cast iron; 1 year on the enamel finish", "weight": {"5 qt": "5.2 kg", "7 qt": "6.4 kg"},
     "materials": "Enameled cast iron; stainless steel lid knob", "box": "Pot, lid",
     "care": "Dishwasher-safe, but hand-washing keeps the enamel glossy. Avoid metal utensils and sudden "
             "temperature changes (thermal shock can crack enamel).",
     "faq": [("What's the maximum oven temperature?", "260°C, lid included."),
             ("The enamel chipped. Is that covered?", "Chipping from impact is not covered; enamel crazing "
              "within the first year is covered by the 1-year enamel warranty.")]}),
    ("Chef's Knife", {"weight": {"8 in": "210 g", "10 in": "260 g"},
     "materials": "High-carbon stainless steel (58 HRC), full tang, G10 handle", "box": "Knife, blade guard",
     "care": "Hand-wash only and dry immediately. Hone weekly; sharpen on a whetstone at 15° per side.",
     "faq": [("Can it go in the dishwasher?", "No. Dishwashers dull and can chip the edge and void the warranty."),
             ("Is it left-handed friendly?", "Yes, the 50/50 bevel works for both hands.")]}),
    ("End-Grain Cutting Board", {"weight": {"walnut": "3.1 kg", "maple": "3.4 kg"},
     "materials": "End-grain hardwood, food-safe mineral oil finish", "box": "Board, rubber feet (pre-fitted)",
     "care": "Oil monthly with food-safe mineral oil. Hand-wash; never soak. Small surface cracks can be "
             "sanded and re-oiled.",
     "faq": [("Why end grain?", "The knife edge slips between wood fibres instead of cutting across them, so "
              "edges stay sharp longer and cuts close up."),
             ("Does it come pre-oiled?", "Yes, but oil it again before first use.")]}),
    ("Gooseneck Pour-Over Kettle", {"weight": {"1.0 L": "1.1 kg", "1.2 L": "1.25 kg"},
     "materials": "Stainless steel body, BPA-free base", "box": "Kettle, base, quick-start card",
     "care": "Descale monthly with a 1:1 water and white vinegar solution. Never immerse the base.",
     "faq": [("The display shows E1. What does that mean?", "E1 means the kettle was switched on empty or ran "
              "dry. Let it cool for 10 minutes, fill it above the MIN line, and switch on again."),
             ("How long does hold mode keep the temperature?", "Up to 60 minutes.")]}),
    ("French Press", {"weight": {"350 ml": "540 g", "1 L": "980 g"},
     "materials": "Double-wall 18/8 stainless steel", "box": "Press, spare filter screen",
     "care": "Dishwasher-safe. Unscrew the filter stack monthly to clean the screens.",
     "faq": [("Will it crack like glass presses?", "No: it's all stainless steel."),
             ("How long does it keep coffee hot?", "About an hour.")]}),
    ("Trailhead Tent", {"weight": {"2-person": "1.9 kg", "3-person": "2.4 kg"},
     "materials": "20D ripstop nylon fly with DWR coating, 3,000 mm hydrostatic head; aluminium poles",
     "box": "Tent body, fly, poles, 10 stakes, guylines, stuff sack, repair sleeve",
     "care": "Never store wet: dry fully within 24 hours. Re-proof the fly yearly. See 'Tent care and "
             "waterproofing'.",
     "faq": [("Is it a 4-season tent?", "No, it's 3-season: not rated for snow loads."),
             ("What's the packed size?", "46 × 15 cm (2-person) or 50 × 17 cm (3-person).")]}),
    ("Summit Backpack", {"weight": {"35 L": "1.4 kg", "50 L": "1.8 kg", "65 L": "2.1 kg"},
     "materials": "210D nylon with PU coating; aluminium frame stay", "box": "Pack, rain cover",
     "care": "Hand-wash with mild soap; air dry. Don't machine-wash (it damages the coating).",
     "faq": [("How do I adjust the torso length?", "Loosen the shoulder-harness Velcro behind the back panel, "
              "slide it to your torso length (marked S/M/L), then press it closed."),
             ("Does it fit a hydration bladder?", "Yes, up to 3 L.")]}),
    ("Daypack", {"weight": {"18 L": "310 g", "24 L": "380 g"},
     "materials": "30D silnylon", "box": "Daypack",
     "care": "Hand-wash; air dry.",
     "faq": [("Is it waterproof?", "Water-resistant, not waterproof: seams aren't taped.")]}),
    ("Canister Camp Stove", {"weight": {"compact": "85 g", "with piezo igniter": "98 g"},
     "materials": "Aluminium and titanium burner", "box": "Stove, hard case",
     "care": "Let it cool before packing. Keep the jet clean; don't use it inside a closed tent.",
     "faq": [("Which fuel does it use?", "Standard threaded isobutane-propane canisters (EN 417). Fuel is "
              "sold separately and can't be shipped by air."),
             ("The piezo igniter stopped sparking.", "Check the electrode gap is 4 mm; light with a match "
              "meanwhile. Igniters are covered for 2 years.")]}),
    ("Down Sleeping Bag", {"weight": {"-5°C": "1.15 kg", "0°C": "0.95 kg", "+5°C": "0.78 kg"},
     "materials": "650-fill responsibly sourced down, 20D nylon shell", "box": "Bag, compression sack, storage sack",
     "care": "Store uncompressed in the storage sack. Wash rarely, with down wash, and tumble-dry low with "
             "dryer balls.",
     "faq": [("What does the temperature rating mean?", "It's the comfort rating (EN/ISO 23537): the lowest "
              "temperature at which a typical person sleeps comfortably in a relaxed position."),
             ("Can I use it below its rating?", "With a liner and warm clothes, a few degrees lower; we don't "
              "recommend it.")]}),
    ("Headlamp", {"weight": {"400 lm": "78 g", "800 lm": "92 g"},
     "materials": "Polycarbonate housing; 1,200 mAh Li-ion battery", "box": "Headlamp, USB-C cable",
     "care": "Charge every 3 months in storage. IPX4: splash-proof, not submersible.",
     "faq": [("It won't charge.", "Use a USB-C cable that carries data (some charge-only cables don't "
              "negotiate). The indicator is red while charging and green when full."),
             ("How long does it last?", "About 5 hours on high, 40 hours on low.")]}),
    ("Squeeze Water Filter", {"weight": {"standard": "85 g", "with 2 L bag": "120 g"},
     "materials": "Hollow-fibre membrane (0.1 micron)", "box": "Filter, backflush syringe",
     "care": "Backflush after every trip. Never let it freeze when wet: ice cracks the fibres invisibly; "
             "replace a filter that may have frozen.",
     "faq": [("Does it remove viruses?", "No. It removes bacteria and protozoa; boil or treat chemically "
              "where viruses are a concern.")]}),
    ("Standing Desk", {"weight": {"120 cm": "32 kg", "140 cm": "35 kg", "160 cm": "38 kg"},
     "materials": "Steel frame, laminated top", "box": "Frame, top, control panel, hardware kit, Allen key",
     "care": "Wipe with a damp cloth. Re-tighten frame bolts after the first month.",
     "faq": [("What's the height range?", "62 to 127 cm."),
             ("The panel shows E2.", "E2 means the legs are out of sync. Hold the down button until the "
              "desk reaches its lowest point and beeps (reset), then release.")]}),
    ("Ergonomic Chair", {"weight": {"mesh": "17 kg", "fabric": "19 kg"},
     "materials": "Aluminium base, class-4 gas lift", "box": "Chair (seat, back, base), casters, hardware",
     "care": "Vacuum fabric; wipe mesh with a damp cloth.",
     "faq": [("What's the weight limit?", "150 kg."),
             ("It slowly sinks.", "The gas lift is failing: covered under the 5-year frame warranty.")]}),
    ("Monitor Arm", {"weight": {"single": "2.8 kg", "dual": "4.6 kg"},
     "materials": "Aluminium arm, steel clamp", "box": "Arm, desk clamp, grommet mount, VESA screws",
     "care": "Adjust the gas-spring tension with the 4 mm Allen key if the monitor drifts.",
     "faq": [("My monitor drifts down.", "Increase the spring tension: turn the hex screw at the elbow "
              "towards + until the monitor stays put."),
             ("Will it hold a 34 in ultrawide?", "If it weighs 9 kg or less and has VESA 75 or 100 mounts.")]}),
    ("Under-Desk Cable Tray", {"weight": {"60 cm": "1.1 kg", "90 cm": "1.5 kg"},
     "materials": "Powder-coated steel", "box": "Tray, 2 clamps",
     "care": "None.",
     "faq": [("What desk thickness do the clamps fit?", "15 to 45 mm.")]}),
    ("Dimmable LED Bulb A19", {"weight": {"2700K warm": "55 g", "4000K neutral": "55 g"},
     "materials": "Polycarbonate diffuser", "box": "Bulb",
     "care": "Not for enclosed fixtures.",
     "faq": [("It flickers on my dimmer.", "Use a trailing-edge (ELV) dimmer and set its low-end trim. "
              "See 'LED bulb compatibility and flicker'."),
             ("What's the wattage equivalent?", "800 lm, about a 60 W incandescent, drawing 8.5 W.")]}),
    ("Smart Bulb", {"weight": {"white": "70 g", "colour": "75 g"},
     "materials": "Polycarbonate diffuser", "box": "Bulb, quick-start card",
     "care": "Not for enclosed fixtures or dimmer circuits.",
     "faq": [("It won't connect to Wi-Fi.", "It needs 2.4 GHz Wi-Fi (not 5 GHz). Reset by switching it off "
              "and on 5 times; it blinks when ready to pair."),
             ("Does it need a hub?", "No.")]}),
    ("Arc Floor Lamp", {"weight": {"brass": "18 kg", "matte black": "18 kg"},
     "materials": "Steel arc, marble base, linen shade", "box": "Base, arc in 3 sections, shade, E27 socket",
     "care": "Dust the shade with a soft brush.",
     "faq": [("Which bulb does it take?", "E27, up to 60 W LED equivalent. Bulb not included.")]}),
    ("Outdoor String Lights", {"weight": {"15 m": "1.3 kg", "30 m": "2.4 kg"},
     "materials": "Shatterproof PC bulbs, IP65 cable", "box": "Lights, 2 spare bulbs, mounting clips",
     "care": "IP65: rain-proof; don't submerge the plug.",
     "faq": [("Can I connect several strings?", "Up to 3 strings end to end.")]}),
    ("VoltPack Power Bank", {"weight": {"10000 mAh": "190 g", "20000 mAh": "350 g"},
     "materials": "Lithium-polymer cells", "box": "Power bank, USB-C cable",
     "care": "Store at 40–60% charge. Stop using it if it swells: see 'Battery safety for power banks'.",
     "faq": [("Will it charge my laptop?", "Laptops that charge from 30 W USB-C, yes (slowly). Larger "
              "laptops need 65 W or more."),
             ("Can I take it on a plane?", "Yes, in carry-on only: both sizes are under 100 Wh.")]}),
    ("Braided USB-C Cable", {"weight": {"1 m": "40 g", "2 m": "65 g"},
     "materials": "Braided nylon jacket, e-marker chip", "box": "Cable",
     "care": "None.",
     "faq": [("Does it carry video?", "No: USB 2.0 data and 100 W charging only.")]}),
    ("GaN Wall Charger", {"weight": {"65 W": "120 g", "100 W": "190 g"},
     "materials": "Gallium nitride power stage", "box": "Charger",
     "care": "Keep vents uncovered.",
     "faq": [("How is power shared between ports?", "One port alone gets the full rating; with several "
              "devices the total is split, with the first USB-C port prioritised.")]}),
    ("Wireless Charging Pad", {"weight": {"15 W": "80 g", "15 W with stand": "210 g"},
     "materials": "Aluminium and silicone", "box": "Pad, USB-C cable (adapter not included)",
     "care": "Remove metal cards from the phone case before charging.",
     "faq": [("It charges slowly.", "15 W needs a Qi2 phone and an adapter of at least 20 W; otherwise it "
              "falls back to 5–7.5 W.")]}),
    ("Commuter Backpack", {"weight": {"20 L": "0.9 kg", "28 L": "1.1 kg"},
     "materials": "Recycled 600D polyester with TPU coating", "box": "Backpack",
     "care": "Spot-clean only.",
     "faq": [("Will a 16 in laptop fit?", "Yes, in the padded sleeve.")]}),
    ("Duffel Bag", {"weight": {"40 L": "0.8 kg", "60 L": "1.0 kg"},
     "materials": "Recycled nylon", "box": "Duffel, shoulder strap",
     "care": "Machine-wash cold, gentle cycle; air dry.",
     "faq": [("Is the 40 L carry-on size?", "Yes for most airlines (55 × 35 × 23 cm when packed).")]}),
    ("Packing Cubes", {"weight": {"set of 3": "210 g", "set of 5": "330 g"},
     "materials": "Ripstop nylon, mesh tops", "box": "Cubes",
     "care": "Machine-wash cold.",
     "faq": [("What sizes are in the set?", "Set of 3: S, M, L. Set of 5: adds an XS and a laundry bag.")]}),
]

GUIDES = {
    "guide-choosing-a-tent": ("Buying guide: choosing a backpacking tent", "guide", """\
Weight versus space is the main trade-off. The Trailhead 2-person (1.9 kg) suits solo hikers and couples who
pack light; the 3-person (2.4 kg) gives two people room for gear, or fits three.

Both are 3-season tents: they handle rain and wind but are not rated for snow loads. For winter mountaineering,
choose a 4-season tent from a specialist.

A 3,000 mm hydrostatic head on the fly is plenty for sustained rain. Keep the DWR coating healthy (see 'Tent care
and waterproofing')."""),
    "guide-sleeping-bag-ratings": ("Sleeping bag temperature ratings explained", "guide", """\
Our bags are labelled with their comfort rating under EN/ISO 23537. Comfort is the temperature at which a typical
person sleeps comfortably lying relaxed. The lower 'limit' rating, for a person curled up, is about 5°C colder.

If you sleep cold, choose a bag rated 5°C below the coldest night you expect. A sleeping pad matters as much as the
bag: most heat is lost to the ground."""),
    "guide-usb-c-power": ("USB-C power: which charger for which device", "guide", """\
USB-C Power Delivery (PD) devices negotiate how much power they draw. A phone draws 20–30 W, a tablet 30–45 W, a
small laptop 45–65 W, a large laptop 90–100 W. A charger can only deliver its rating; a cable must be rated for the
current (our braided cables carry 100 W).

The VoltPack power banks output up to 30 W: enough for phones and tablets, slow for laptops. The 65 W GaN charger
handles most laptops; the 100 W model handles large ones."""),
    "guide-water-treatment": ("Treating water on the trail", "guide", """\
Hollow-fibre filters (like our squeeze filter) remove bacteria and protozoa but not viruses. In places where viruses
are a concern (near human settlements, or abroad with poor sanitation), add chemical treatment or boil.

Freezing destroys hollow-fibre filters without visible damage. In cold weather, sleep with the filter in your bag."""),
    "troubleshoot-smart-bulb": ("Troubleshooting: smart bulb won't pair", "troubleshooting", """\
1. The bulb needs a 2.4 GHz network. Many routers broadcast 2.4 and 5 GHz under one name; temporarily split them.
2. Reset the bulb: switch it off and on five times, about one second each. It blinks when it's in pairing mode.
3. Keep the phone within 5 m during pairing.
4. Smart bulbs don't work on dimmer circuits: set any dimmer to full, or replace it with a normal switch."""),
    "troubleshoot-kettle": ("Troubleshooting: gooseneck kettle error codes", "troubleshooting", """\
- E1: switched on empty or boiled dry. Cool 10 minutes, fill above MIN, restart.
- E2: temperature sensor fault. Unplug for 1 minute; if it persists, contact support (covered by warranty).
- E3: base not detecting the kettle. Clean the contacts and re-seat the kettle.
Limescale makes the kettle louder and slower: descale monthly in hard-water areas."""),
    "troubleshoot-standing-desk-noises": ("Troubleshooting: standing desk noises and wobble", "troubleshooting", """\
Wobble at full height is normal up to about 1 cm at the top edge. More than that usually means loose frame bolts:
re-tighten all crossbar bolts with the included Allen key.

Grinding or clicking while moving: run the reset (hold down until it beeps at the lowest point). If one leg lags or
the noise persists, a motor may be failing: motors are covered for 1 year."""),
    "troubleshoot-headlamp": ("Troubleshooting: headlamp charging and modes", "troubleshooting", """\
If the headlamp doesn't charge, try a different USB-C cable (some cables are charge-only and don't negotiate) and a
5 V adapter. The indicator is red while charging and green when full; a full charge takes about 3 hours.

Lockout mode prevents it switching on in your pack: hold the button for 4 seconds to lock or unlock (it blinks
twice)."""),
    "ops-carrier-cutoffs": ("Shipping: carrier cut-off times", "ops", """\
Orders placed before 14:00 local warehouse time on a business day ship the same day. Orders after the cut-off ship
the next business day. Weekend orders ship Monday.

Fuel canisters and power banks over 100 Wh ship by ground only. We don't ship fuel canisters internationally."""),
}

ARCHIVED = {
    "warranty-2024": ("Warranty coverage (2024)", """\
ARCHIVED: this article describes our 2024 warranty and is kept for reference only.

- Electronics accessories: **6 months**.
- Lighting: 1 year.
- Outdoor gear: 1 year.
- Home office furniture: 3 years on frames.
- Kitchen: lifetime on cast iron; 6 months on everything else."""),
    "plus-membership-2024": ("Shopfront Plus membership (2024)", """\
ARCHIVED: this article describes Plus as it was in 2024.

Plus costs $39 a year and includes free standard shipping on orders over $25 and a 40-day refund window."""),
}


def _clean(text: str) -> str:
    text = html.unescape(re.sub(r"<br\s*/?>", " ", text))
    return re.sub(r"\s+", " ", text).strip()


def _front(**kv) -> str:
    return "---\n" + "".join(f"{k}: {v}\n" for k, v in kv.items()) + "---\n\n"


def _family(name: str) -> tuple[str, dict, str]:
    for fam, spec in FAMILIES:
        if name.startswith(fam):
            m = re.search(r"\(([^)]*)\)\s*$", name)
            return fam, spec, m.group(1) if m else ""
    raise KeyError(name)


def product_page(sku: str, name: str, category: str, price_cents: int, active: bool, description: str) -> str:
    fam, spec, variant = _family(name)
    weight = spec["weight"].get(variant, next(iter(spec["weight"].values())))
    lines = [_front(id=f"product-{sku}", title=name, type="product", sku=sku, category=category,
                    status="current" if active else "discontinued", updated="2026-10-01"),
             f"# {name}\n\n",
             f"SKU {sku} · {category} · ${price_cents / 100:.2f}\n\n",
             ("" if active else "**Discontinued**: no longer sold. Existing orders are still covered by the "
              "warranty and refund policy.\n\n"),
             _clean(description) + "\n\n",
             "## Specifications\n",
             f"- Weight: {weight}\n- Materials: {spec['materials']}\n- In the box: {spec['box']}\n\n",
             f"## Care\n{spec['care']}\n\n",
             f"## Warranty\n{spec.get('warranty', WARRANTY[category])}, counted from delivery. See 'Warranty "
             f"coverage'.\n\n",
             "## Questions customers ask\n"]
    for q, a in spec["faq"]:
        lines.append(f"**{q}** {a}\n\n")
    return "".join(lines).rstrip() + "\n"


def _seeded_products() -> list[tuple]:
    """(sku, name, category, price_cents, active, description) from a freshly seeded database (deterministic)."""
    import sqlite3
    import tempfile

    from shopfront.seed import build
    with tempfile.TemporaryDirectory() as d:
        build(Path(d) / "shop.db", out_dir=Path(d))
        conn = sqlite3.connect(Path(d) / "shop.db")
        rows = conn.execute("SELECT sku, name, category, price_cents, active, description FROM products "
                            "ORDER BY id").fetchall()
        conn.close()
    return rows


PREVIOUS_MODELS = {2024: 1.18, 2025: 1.08}     # model year -> weight factor (older models were heavier)


def _scale_weight(w: str, f: float) -> str:
    n, unit = re.match(r"([\d.]+)\s*(\w+)", w).groups()
    v = float(n) * f
    return f"{v:.2f} {unit}".replace(".00 ", " ") if unit == "kg" else f"{round(v)} {unit}"


def previous_model_page(year: int, sku: str, name: str, category: str, description: str) -> str:
    """Archived pages for earlier model years: realistic near-duplicates with STALE specs (the retrieval trap)."""
    fam, spec, variant = _family(name)
    weight = _scale_weight(spec["weight"].get(variant, next(iter(spec["weight"].values()))), PREVIOUS_MODELS[year])
    old_warranty = {"electronics-accessories": "6 months", "lighting": "1 year", "outdoor": "1 year",
                    "home-office": "3 years on the frame", "kitchen": "6 months (cast iron: lifetime)",
                    "bags": "6 months"}[category] if year == 2024 else spec.get("warranty", WARRANTY[category])
    # why two styles: 2024 pages announce themselves ("ARCHIVED", "2024 model"); 2025 pages look exactly like a
    # current page, and only the status METADATA says otherwise. Real archives are mostly the second kind.
    banner = year == 2024
    title = f"{name}, {year} model" if banner else name
    return (_front(id=f"product-{sku}-{year}", title=title, type="product", sku=sku,
                   category=category, status="archived", updated=f"{year}-03-01")
            + f"# {title}\n\n"
            + (f"ARCHIVED: the {year} model of SKU {sku}, no longer sold. Specifications differ from the current "
               f"model.\n\n" if banner else f"SKU {sku} · {category}\n\n")
            + f"{_clean(description)}\n\n## Specifications\n- Weight: {weight}\n"
              f"- Materials: {spec['materials']}\n\n## Warranty\n{old_warranty}"
            + (f" (as sold in {year}).\n" if banner else ", counted from delivery.\n"))


CATEGORY_NAMES = {"kitchen": "Kitchen", "outdoor": "Outdoor gear", "home-office": "Home office",
                  "lighting": "Lighting", "electronics-accessories": "Electronics accessories", "bags": "Bags"}


def handbook(category: str, families: list[tuple[str, dict]]) -> str:
    """One long care handbook per category. why: everything else in the KB is short; these give the chunker real
    work (sections of several thousand characters), so chunk size and overlap actually change results."""
    care = "\n\n".join(f"**{fam}.** {spec['care']} Materials: {spec['materials']}. In the box: {spec['box']}."
                        for fam, spec in families)
    warranty = "\n".join(f"- {fam}: {spec.get('warranty', WARRANTY[category])}." for fam, spec in families)
    name = CATEGORY_NAMES[category]
    return (_front(id=f"handbook-{category}", title=f"{name} care handbook", type="guide", status="current",
                   updated="2026-07-01")
            + f"# {name} care handbook\n\nThis handbook collects the care, materials and warranty notes for every "
              f"{name.lower()} product family we sell. Product pages have the same notes plus specifications and "
              f"customer questions.\n\n## Care, materials and what's in the box\n\n{care}\n\n"
              f"## Warranty by product family\n\nCounted from delivery; see 'Warranty coverage' for how to "
              f"claim.\n\n{warranty}\n")


def build_kb(out: Path = KB, products=None) -> list[Path]:
    products = products if products is not None else _seeded_products()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    written = []
    for src in sorted(HELP.glob("*.md")):
        text = src.read_text()
        # help-center files have front matter without id/type; add them
        body = text.split("---", 2)[2] if text.startswith("---") else text
        meta = dict(re.findall(r"^(\w+): (.*)$", text.split("---", 2)[1], re.M)) if text.startswith("---") else {}
        p = out / f"help-{src.stem}.md"
        p.write_text(_front(id=f"help-{src.stem}", title=meta.get("title", src.stem), type="help",
                            status=meta.get("status", "current"), updated=meta.get("updated", "2026-01-01"))
                     + body.lstrip())
        written.append(p)
    for sku, name, category, price_cents, active, description in products:
        p = out / f"product-{sku}.md"
        p.write_text(product_page(sku, name, category, price_cents, bool(active), description))
        written.append(p)
        for year in PREVIOUS_MODELS:
            p = out / f"product-{sku}-{year}.md"
            p.write_text(previous_model_page(year, sku, name, category, description))
            written.append(p)
    for category in CATEGORY_NAMES:
        fams = [(f, sp) for f, sp in FAMILIES if any(n.startswith(f) and c == category
                                                      for _, n, c, *_ in products)]
        p = out / f"handbook-{category}.md"
        p.write_text(handbook(category, fams))
        written.append(p)
    for doc_id, (title, kind, body) in GUIDES.items():
        p = out / f"{doc_id}.md"
        p.write_text(_front(id=doc_id, title=title, type=kind, status="current", updated="2026-06-15")
                     + f"# {title}\n\n{body.strip()}\n")
        written.append(p)
    for doc_id, (title, body) in ARCHIVED.items():
        p = out / f"{doc_id}.md"
        p.write_text(_front(id=doc_id, title=title, type="help", status="archived", updated="2024-03-01")
                     + f"# {title}\n\n{body.strip()}\n")
        written.append(p)
    return written


if __name__ == "__main__":
    files = build_kb()
    words = sum(len(f.read_text().split()) for f in files)
    print(f"wrote {len(files)} documents ({words:,} words) to {KB}")
