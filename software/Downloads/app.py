#!/usr/bin/env python3
"""
Rulebook app: upload a city's recycling/trash rules (a file or pasted text) and turn them into the
rulebook the sorter uses.

    python3 app.py                 # then open the address it prints, from a phone or laptop on the same Wi-Fi
    python3 app.py --local-only    # only reachable from the Pi itself
    python3 app.py --port 8080

How it works: pick a city, type your own rules, or upload a city's rules document. Documents are read on the
Pi itself: it finds the items and the words around them and shows the sentence each rule
came from. You check everything before the can uses it.
Needs: pip install flask pypdf python-docx
"""
import argparse
import hmac
import io
import json
import os
import re
import secrets
import socket
import sys
import time

from flask import Flask, abort, redirect, render_template_string, request, session, url_for

import rulebook as rbk

HERE = os.path.dirname(os.path.abspath(__file__))
DRAFT_DIR = os.path.join(HERE, "drafts")
CODE_FILE = os.path.expanduser("~/.sorter_app_code")
SECRET_FILE = os.path.expanduser("~/.sorter_app_secret")
MAX_UPLOAD = 10 * 1024 * 1024
ALLOWED = {".txt", ".md", ".markdown", ".pdf", ".docx"}


def read_private(path, make):
    """Read a small secret file, creating it (readable only by you) the first time."""
    try:
        with open(path) as f:
            value = f.read().strip()
        if value:
            return value
    except OSError:
        pass
    value = make()
    old = os.umask(0o077)
    try:
        with open(path, "w") as f:
            f.write(value + "\n")
    finally:
        os.umask(old)
    return value


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD
app.secret_key = read_private(SECRET_FILE, lambda: secrets.token_hex(32))
ACCESS_CODE = read_private(CODE_FILE, lambda: secrets.token_urlsafe(6))


# ---------- reading the uploaded document ----------

def extract_text(filename, data):
    ext = os.path.splitext(filename.lower())[1]
    if ext not in ALLOWED:
        raise ValueError("Please upload a .pdf, .docx, .md or .txt file, or paste the text instead.")
    if ext == ".txt":
        return data.decode("utf-8", errors="replace")
    if ext in (".md", ".markdown"):
        return markdown_to_text(data.decode("utf-8", errors="replace"))
    if ext == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ValueError("That PDF is password-protected.")
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    import docx
    d = docx.Document(io.BytesIO(data))
    parts = [p.text for p in d.paragraphs]
    for table in d.tables:
        for row in table.rows:
            parts.append(" | ".join(c.text for c in row.cells))
    return "\n".join(parts)


def markdown_to_text(md):
    """Markdown -> plain lines the reader understands: headings, list items and table cells each on a line,
    with the formatting marks (#, **, _, `, links, images, HTML tags) removed."""
    out, in_code = [], False
    for line in md.splitlines():
        t = line.strip()
        if t.startswith(("```", "~~~")):
            in_code = not in_code
            continue
        if in_code or re.fullmatch(r"[-*_=\s]{3,}", t or "x") or re.fullmatch(r"\|?[\s:|-]+\|?", t or "x"):
            continue                                            # code blocks, rules (---), table dividers
        t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", t)            # images
        t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)        # [text](link) -> text
        t = re.sub(r"<[^>]+>", " ", t)                          # HTML tags
        t = re.sub(r"^#{1,6}\s*", "", t)                        # headings
        t = re.sub(r"^(?:>\s*)+", "", t)                         # quotes
        t = re.sub(r"^(?:[-*+]|\d+[.)])\s+(?:\[[ xX]\]\s+)?", "", t)  # list markers and checkboxes
        t = re.sub(r"(\*\*|__|\*|_|`|~~)", "", t)               # bold, italic, code, strikethrough
        if "|" in t:                                            # table row: keep the row together
            out.append(" - ".join(c.strip() for c in t.strip("|").split("|") if c.strip()))
        elif t:
            out.append(t)
    return "\n".join(out)


# ---------- drafts (a rulebook waiting for review) ----------

def save_draft(rb):
    os.makedirs(DRAFT_DIR, exist_ok=True)
    draft_id = secrets.token_hex(8)
    with open(os.path.join(DRAFT_DIR, draft_id + ".json"), "w") as f:
        json.dump(rb, f)
    return draft_id


def load_draft(draft_id):
    if not re.fullmatch(r"[0-9a-f]{16}", draft_id or ""):
        abort(404)
    try:
        with open(os.path.join(DRAFT_DIR, draft_id + ".json")) as f:
            return rbk.clean(json.load(f))
    except (OSError, ValueError):
        abort(404)


def drop_draft(draft_id):
    try:
        os.remove(os.path.join(DRAFT_DIR, draft_id + ".json"))
    except OSError:
        pass


BIN_ICONS = {'recycling': '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7.5 13.5 5 17.8c-.4.7.1 1.7 1 1.7h5M16.5 13.5l2.5 4.3c.4.7-.1 1.7-1 1.7h-3M9.3 7.3l1.8-3.1c.4-.7 1.4-.7 1.8 0l2.4 4.1M13.5 17.5l1.5 2-1.5 2M15 8.8l.9-2.3 2.3.8M6.6 12l2.4.2-.5 2.4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>', 'trash': '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4.5 7h15M9.5 7V5.2c0-.4.3-.7.7-.7h3.6c.4 0 .7.3.7.7V7M6.5 7l.9 11.6c.1.8.7 1.4 1.5 1.4h6.2c.8 0 1.4-.6 1.5-1.4L17.5 7M10 11v5M14 11v5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>', 'special': '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10.3 4.6 3.4 17a2 2 0 0 0 1.7 3h13.8a2 2 0 0 0 1.7-3L13.7 4.6a2 2 0 0 0-3.4 0zM12 10v4M12 17h.01" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>'}

# ---------- login + CSRF ----------

@app.before_request
def guard():
    if request.endpoint in ("login", "static"):
        return
    if not session.get("ok"):
        return redirect(url_for("login"))
    if request.method == "POST":
        if not hmac.compare_digest(request.form.get("csrf", ""), session.get("csrf", "x")):
            abort(400)


def csrf():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


app.jinja_env.globals["csrf"] = csrf
app.jinja_env.globals["BIN_ICONS"] = BIN_ICONS


@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    if request.method == "POST":
        if hmac.compare_digest(request.form.get("code", "").strip(), ACCESS_CODE):
            session["ok"] = True
            return redirect(url_for("home"))
        time.sleep(1)  # slows down guessing
        error = "That code is not right."
    return page(LOGIN, "Sign in", error=error)


# ---------- pages ----------

@app.route("/")
def home():
    active = rbk.load_active()
    groups = {}
    for slug, rb in rbk.list_presets():
        city = rb["city"]
        st = city.rsplit(",", 1)[1].strip().split()[0].upper() if "," in city else ""
        state = STATES.get(st, "General starting points")
        groups.setdefault(state, []).append((slug, city))
    preset_groups = sorted(groups.items(), key=lambda kv: (kv[0] == "General starting points", kv[0]))
    # Show a city in the big headline only when the rules in use are one of the listed cities.
    city_picked = any(c == active["city"] for cities in groups.values() for _, c in cities)
    own_rules = "" if city_picked or active["city"].startswith("(no") else active["city"]
    bins = {"recycling": [], "trash": [], "special": []}
    for key, info in rbk.ITEM_TYPES.items():
        r = active["rules"][key]
        bins[r["bin"]].append((info[0].split(" (")[0], r["reason"]))
    return page(HOME, "EZtrash", active=active, city_picked=city_picked, own_rules=own_rules, bins=bins, cov=model_coverage(), preset_groups=preset_groups,
                saved=rbk.list_saved(), msg=request.args.get("msg", ""), err=request.args.get("err", ""))


STATES = {"AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
          "CT": "Connecticut", "DC": "District of Columbia", "DE": "Delaware", "FL": "Florida", "GA": "Georgia",
          "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
          "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts",
          "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
          "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
          "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
          "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
          "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
          "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming"}


BY_HAND = "made by hand"


@app.route("/manual", methods=["POST"])
def manual():
    """Start a rulebook without any document: from the safe defaults, or from a copy of a saved one."""
    city = request.form.get("city", "").strip()[:100]
    if not city:
        return redirect(url_for("home", err="Please enter a name for these rules (a city, a state, or anything)."))
    start = request.form.get("start", "defaults")
    if start != "defaults":
        try:
            rb = rbk.load(os.path.join(rbk.RULEBOOK_DIR, rbk.slugify(start) + ".json"))
        except (OSError, ValueError):
            abort(404)
        rb["city"] = city
        rb["created"] = rbk.default_rulebook()["created"]
    else:
        rb = rbk.default_rulebook(city)
        rb["source_name"] = BY_HAND
        for r in rb["rules"].values():
            r["status"] = "manual"
    return redirect(url_for("review", draft_id=save_draft(rb)))


@app.route("/write", methods=["GET", "POST"])
def write():
    """Write all the rules as text, with a live preview of where everything goes."""
    if request.method == "POST":
        name = request.form.get("city", "").strip()[:100]
        text = request.form.get("rules", "")[:8000]
        if not name:
            return redirect(url_for("write", err="Give your rules a name."))
        rb, notes = rbk.parse_quick(text, name)
        rb["source_name"] = request.form.get("source", "").strip()[:200] or "written by hand"
        rb["contacts"] = {k: request.form.get("contact_" + k, "").strip()[:120] for k in ("recycling", "hazardous")}
        activate = bool(request.form.get("activate"))
        rbk.save(rb, activate=activate)
        msg = f"Saved {rb['city']}" + (" and the can is using it now." if activate else ".")
        skipped = [n for n in notes if not n.startswith("No rules were understood")]
        if skipped:
            msg += f" {len(skipped)} line(s) were skipped because they weren't understood."
        return redirect(url_for("home", msg=msg))

    active = rbk.load_active()
    options = [{"label": "Blank (everything to trash, dangerous items to special)", "name": "",
                "text": "recycling: \ntrash: everything else\nspecial, hazardous: spray cans, medicine, needles, batteries, light bulbs\n"
                        "special, drop-off: electronics, cables, building materials", "source": "written by hand",
                "contacts": {"recycling": "", "hazardous": ""}}]
    if not active["city"].startswith("(no"):
        options.append({"label": f"Rules in use now: {active['city']}", "name": active["city"],
                        "text": rbk.rulebook_to_text(active), "source": active["source_name"], "contacts": active["contacts"]})
    for slug, rb in rbk.list_saved():
        options.append({"label": f"Saved: {rb['city']}", "name": rb["city"], "text": rbk.rulebook_to_text(rb),
                        "source": rb["source_name"], "contacts": rb["contacts"], "key": "s:" + slug})
    for slug, rb in rbk.list_presets():
        options.append({"label": rb["city"], "name": rb["city"], "text": rbk.rulebook_to_text(rb),
                        "source": f"started from {rb['city']}", "contacts": rb["contacts"], "key": "p:" + slug})
    want = request.args.get("from", "")
    start = next((o for o in options if o.get("key") == want), None)
    if start is None:
        start = options[1] if want == "active" and len(options) > 1 else options[0]
    return page(WRITE, "Write your rules", options=options, start=start, err=request.args.get("err", ""),
                words=[[p, t] for p, t in rbk._QUICK_WORDS],
                items={k: {"name": v[0].split(" (")[0], "bin": v[1], "reason": v[2]} for k, v in rbk.ITEM_TYPES.items()},
                text_names=rbk.TEXT_NAMES)


@app.route("/make", methods=["POST"])
def make():
    """Make your own rules: a starting point (safe defaults, a city, or a saved set), plus optional typed rules,
    then the editor."""
    city = request.form.get("city", "").strip()[:100]
    if not city:
        return redirect(url_for("home", err="Give your rules a name (like 'My school')."))
    start = request.form.get("start", "defaults")
    try:
        if start.startswith("p:"):
            base = rbk.load_preset(start[2:])
            base["source_name"] = f"started from {base['city']}"
        elif start.startswith("s:"):
            base = rbk.load(os.path.join(rbk.RULEBOOK_DIR, rbk.slugify(start[2:]) + ".json"))
            base["source_name"] = f"started from {base['city']}"
        else:
            base = rbk.default_rulebook(city)
            base["source_name"] = BY_HAND
            for r in base["rules"].values():
                r["status"] = "manual"
    except (OSError, ValueError):
        abort(404)
    base["city"], base["created"] = city, rbk.default_rulebook()["created"]
    notes = []
    text = request.form.get("rules", "").strip()
    if text:
        base, notes = rbk.parse_quick(text[:5000], city, base)
        notes = [n for n in notes if not n.startswith("No rules were understood")] or notes
    return redirect(url_for("review", draft_id=save_draft(base), warn="|".join(n.replace("|", "/") for n in notes)))


ITEM_GROUPS = [
    ("Metal", ["aluminum_steel_can", "spray_can"]),
    ("Plastic", ["plastic_bottle", "plastic_container", "plastic_cup", "plastic_bag"]),
    ("Paper", ["cardboard", "paper", "newspaper", "paper_cup", "carton"]),
    ("Glass", ["glass"]),
    ("Everyday trash", ["cigarette_butt", "gloves_masks", "other_trash"]),
    ("Hazardous and electronics", ["battery", "light_bulb", "medicine", "sharps", "electronics", "cables", "building_material"]),
]
assert sorted(k for _, ks in ITEM_GROUPS for k in ks) == sorted(rbk.ITEM_TYPES)


@app.route("/quick", methods=["POST"])
def quick():
    """Rules typed in plain words (no document, no AI). Goes to the review table before anything is used."""
    city = request.form.get("city", "").strip()[:100]
    text = request.form.get("rules", "").strip()
    if not city or not text:
        return redirect(url_for("home", err="Enter a name and at least one rule."))
    rb, notes = rbk.parse_quick(text[:5000], city)
    rb["source_name"] = BY_HAND
    return redirect(url_for("review", draft_id=save_draft(rb), warn="|".join(n.replace("|", "/") for n in notes)))


def model_coverage():
    """Compare what the trained model can recognize with the item types a rulebook covers."""
    path = os.path.join(HERE, "model_local.npz")
    if not os.path.exists(path):
        return None
    try:
        import numpy as np
        classes = [str(c) for c in np.load(path, allow_pickle=False)["classes"]]
    except Exception:
        return None
    unknown = [c for c in classes if c not in rbk.ITEM_TYPES and c != rbk.EMPTY]
    missing = [k for k in rbk.ITEM_TYPES if k not in classes]
    return {"classes": classes, "unknown": unknown, "missing": missing}


@app.route("/preset", methods=["POST"])
def use_preset_form():
    slug = request.form.get("slug", "")
    if not slug:
        return redirect(url_for("home", err="Select a city first."))
    return use_preset(slug)


@app.route("/preset/<slug>", methods=["POST"])
def use_preset(slug):
    """Start from a ready-made city rulebook. It still goes through the review table first."""
    try:
        rb = rbk.load_preset(slug)
    except (OSError, ValueError):
        abort(404)
    return redirect(url_for("review", draft_id=save_draft(rb), warn="Starting rules: check each row against your city's current list."))


@app.route("/import", methods=["POST"])
def import_file():
    up = request.files.get("file")
    if not up or not up.filename:
        return redirect(url_for("home", err="Choose a rulebook (.json) file."))
    try:
        rb = rbk.import_rulebook(up.read())
    except ValueError as e:
        return redirect(url_for("home", err=f"Could not import: {e}."))
    return redirect(url_for("review", draft_id=save_draft(rb)))


@app.route("/export/<slug>")
def export(slug):
    path = os.path.join(rbk.RULEBOOK_DIR, rbk.slugify(slug) + ".json")
    if not os.path.exists(path):
        abort(404)
    with open(path) as f:
        body = f.read()
    return app.response_class(body, mimetype="application/json",
                              headers={"Content-Disposition": f"attachment; filename={rbk.slugify(slug)}.json"})


@app.route("/edit-active", methods=["POST"])
def edit_active():
    rb = rbk.load_active()
    if rb["city"].startswith("(no"):
        rb["city"] = "My rules"
        rb["source_name"] = BY_HAND
        for r in rb["rules"].values():
            r["status"] = "manual"
    return redirect(url_for("review", draft_id=save_draft(rb)))


@app.route("/analyze", methods=["POST"])
def analyze():
    city = request.form.get("city", "").strip()
    pasted = request.form.get("text", "").strip()
    upload = request.files.get("file")
    if not city:
        return redirect(url_for("home", err="Please enter the city or state name."))
    try:
        if upload and upload.filename:
            text, source = extract_text(upload.filename, upload.read()), upload.filename
        elif pasted:
            text, source = markdown_to_text(pasted), "pasted text"   # pasted Markdown works too
        else:
            return redirect(url_for("home", err="Upload a file or paste some text."))
    except Exception as e:
        return redirect(url_for("home", err=f"Could not read that file: {e}"))
    if len(text.strip()) < 40:
        return redirect(url_for("home", err="Almost no text was found. If it is a scanned PDF, "
                                            "paste the text in instead."))
    rb, warnings = rbk.extract_rulebook_local(text, city, source)   # read on the Pi itself
    return redirect(url_for("review", draft_id=save_draft(rb), warn="|".join(w.replace("|", "/") for w in warnings)))


@app.route("/review/<draft_id>", methods=["GET", "POST"])
def review(draft_id):
    draft = load_draft(draft_id)
    if request.method == "POST":
        out = rbk.default_rulebook(request.form.get("city", "").strip() or draft["city"])
        out["source_name"], out["created"] = draft["source_name"], draft["created"]
        out["contacts"] = {k: request.form.get("contact_" + k, "").strip() for k in ("recycling", "hazardous")}
        for key in rbk.ITEM_TYPES:
            old = draft["rules"][key]
            bin_ = request.form.get("bin_" + key, old["bin"])
            reason = request.form.get("reason_" + key, old["reason"])
            changed = (bin_, reason) != (old["bin"], old["reason"])
            out["rules"][key] = dict(old, bin=bin_, reason=reason,
                                     status="edited" if changed else old["status"])
        rbk.save(out, activate=bool(request.form.get("activate")))
        drop_draft(draft_id)
        return redirect(url_for("home", msg=f"Saved {out['city']}" + (" and activated it." if request.form.get("activate") else ".")))
    warnings = [w for w in request.args.get("warn", "").split("|") if w]
    by_hand = draft["source_name"] == BY_HAND
    n_default = 0 if by_hand else sum(1 for r in draft["rules"].values() if r["status"] == "default")
    n_unverified = sum(1 for r in draft["rules"].values() if r["status"] == "from_document" and not r["quote_verified"])
    from_doc = any(r["status"] == "from_document" for r in draft["rules"].values()) and not by_hand
    return page(REVIEW, "Edit rules", rb=draft, draft_id=draft_id, types=rbk.ITEM_TYPES, groups=ITEM_GROUPS,
                warnings=warnings, n_default=n_default if from_doc else 0, n_unverified=n_unverified, from_doc=from_doc)


@app.route("/edit/<slug>", methods=["POST"])
def edit(slug):
    path = os.path.join(rbk.RULEBOOK_DIR, rbk.slugify(slug) + ".json")
    try:
        rb = rbk.load(path)
    except (OSError, ValueError):
        abort(404)
    return redirect(url_for("review", draft_id=save_draft(rb)))


@app.route("/activate/<slug>", methods=["POST"])
def activate(slug):
    try:
        rb = rbk.activate(slug)
    except (OSError, ValueError):
        abort(404)
    return redirect(url_for("home", msg=f"{rb['city']} is now active. The can picks it up within a moment."))


@app.route("/delete/<slug>", methods=["POST"])
def delete(slug):
    rbk.delete_saved(slug)
    return redirect(url_for("home", msg="Deleted."))


# ---------- templates ----------

SHELL = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<script>try{var t=localStorage.getItem("eztrash-theme");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t;}catch(e){}</script><title>{{ title if title == "EZtrash" else title ~ " - EZtrash" }}</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg viewBox='0 0 64 64' xmlns='http://www.w3.org/2000/svg'%3E%3Cdefs%3E%3CclipPath id='c0C9'%3E%3Cpath d='M12.60 23.0H51.40L47.55 50.0Q47.30 53.0 44.30 53.0H20.10Q17.10 53.0 16.85 50.0Z'/%3E%3C/clipPath%3E%3C/defs%3E%3Crect width='64' height='64' rx='15' fill='%23C9DA3F'/%3E%3Cpath d='M27.5 13.6v-1.8c0-1 .8-1.8 1.8-1.8h5.4c1 0 1.8.8 1.8 1.8v1.8' fill='none' stroke='%2313392B' stroke-width='2.6' stroke-linecap='round'/%3E%3Crect x='9.5' y='13.5' width='45' height='5.6' rx='2.8' fill='%2313392B'/%3E%3Cpath d='M11.60 23.00 L31.40 23.00 L31.40 28.00 L12.27 28.00Z M14.93 48.00 L31.40 48.00 L31.40 54.00 L15.60 54.00Z M11.60 23.00 L18.00 23.00 L22.00 54.00 L15.60 54.00Z M14.60 35.50 L27.40 35.50 L27.40 40.50 L14.60 40.50Z M31.40 23.00 L52.40 23.00 L51.80 28.00 L31.40 28.00Z M31.40 48.00 L49.40 48.00 L48.80 54.00 L31.40 54.00Z M44.10 27.70 L51.80 27.70 L40.60 48.30 L33.30 48.30Z' fill='%2313392B' clip-path='url(%23c0C9)'/%3E%3C/svg%3E">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible:wght@400;700&family=Bricolage+Grotesque:opsz,wght@12..96,500;12..96,700;12..96,800&display=swap" rel="stylesheet">
<style>
:root{
--forest:#13392B;--forest-2:#1B4A38;--cart:#1F7A4D;--leaf:#34A563;--slate:#3E544A;--chartreuse:#C9DA3F;
--sage:#EEF3EC;--paper:#FBFDF9;--line:#D3DFD5;--ink:#13261D;--mute:#53675C;--bad:#A3322B;
--rec:#34A563;--rec-bg:#E6F4EA;--tra:#3E544A;--tra-bg:#E9EEEA;--spe:#C9DA3F;--spe-bg:#F5F8DC;
--display:"Bricolage Grotesque",ui-sans-serif,system-ui,sans-serif;--body:"Atkinson Hyperlegible",ui-sans-serif,system-ui,sans-serif;
--accent:#1F7A4D;--accent-ink:#fff;--card:#FBFDF9;--bg:#EEF3EC;--warn:#7A6A00}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){
--sage:#0E1E17;--paper:#13271E;--line:#24402F;--ink:#E3EFE6;--mute:#93AE9D;--bad:#F08A80;--forest:#0A1A13;--forest-2:#10281D;
--cart:#3DB873;--rec-bg:#123222;--tra-bg:#18241E;--spe-bg:#252A0C;--tra:#8FA79A;--accent:#3DB873;--accent-ink:#06150D;
--card:#13271E;--bg:#0E1E17;--warn:#D6C55A}}
:root[data-theme=dark]{
--sage:#0E1E17;--paper:#13271E;--line:#24402F;--ink:#E3EFE6;--mute:#93AE9D;--bad:#F08A80;--forest:#0A1A13;--forest-2:#10281D;
--cart:#3DB873;--rec-bg:#123222;--tra-bg:#18241E;--spe-bg:#252A0C;--tra:#8FA79A;--accent:#3DB873;--accent-ink:#06150D;
--card:#13271E;--bg:#0E1E17;--warn:#D6C55A}
:root{color-scheme:light}:root[data-theme=dark]{color-scheme:dark}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){color-scheme:dark}}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--sage);color:var(--ink);font:17px/1.55 var(--body)}
h1,h2,h3,.word,.city{font-family:var(--display);letter-spacing:-.015em}
h1{font-size:2rem;line-height:1.1;font-weight:800;margin:22px 0 6px}
h2{font-size:1.2rem;font-weight:700;margin:0 0 10px}
a{color:var(--cart);font-weight:700;text-underline-offset:3px}
main{max-width:840px;margin:0 auto;padding:0 16px 56px}

/* header: the top of the sign */
header{background:var(--forest);color:#EEF3EC}
.bar{max-width:840px;margin:0 auto;padding:14px 16px 6px;display:flex;align-items:center}
.brand{display:flex;align-items:center;gap:10px;color:#F3F8EF;text-decoration:none;font-weight:inherit}
.logo{width:38px;height:38px;display:block}
.word{font-size:1.35rem;font-weight:800;letter-spacing:-.03em}
.bar{justify-content:space-between}
.theme{background:transparent;border:1.5px solid #3D6B55;color:#C9DA3F;width:40px;height:40px;padding:0;border-radius:10px;
display:grid;place-items:center;cursor:pointer}
.theme:hover{background:#1B4A38;filter:none}.theme svg{width:20px;height:20px}
.theme .moon{display:block}.theme .sun{display:none}
:root[data-theme=dark] .theme .moon{display:none}:root[data-theme=dark] .theme .sun{display:block}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]) .theme .moon{display:none}:root:not([data-theme=light]) .theme .sun{display:block}}

/* the sign band (home only): forest green, full width */
.band{background:var(--forest);color:#EEF3EC;box-shadow:0 0 0 100vmax var(--forest);clip-path:inset(0 -100vmax);padding:19px 0 30px;margin:-1px 0 28px}
.band .label{font-size:1rem;color:#A9C7B4;margin:0}
.band .city{font-size:clamp(2.2rem,7vw,3.6rem);font-weight:800;line-height:1;margin:4px 0 18px;color:#fff;letter-spacing:-.035em}
.band .city.none{color:transparent;-webkit-text-stroke:1.5px #6E9A82;text-stroke:1.5px #6E9A82}
.band select:invalid{color:#8FB3A0;border-style:dashed;border-color:#5C8A73}
.band select option{color:var(--ink);background:var(--paper)}
.band select{background-color:var(--forest-2);color:#fff;border:1.5px solid #3D6B55;
background-image:linear-gradient(45deg,transparent 50%,#C9DA3F 50%),linear-gradient(135deg,#C9DA3F 50%,transparent 50%)}
.band .pick button{background:var(--chartreuse);color:var(--forest)}
.band .hint{font-size:.92rem;color:#A9C7B4;margin:12px 0 0}
.band .hint a{color:#C9DA3F}
.band .edit{color:#C9DA3F;font-size:.95rem}

/* forms */
label{display:block;font-weight:700;font-size:.95rem;margin:14px 0 6px}
input[type=text],input[type=password],textarea,select{width:100%;padding:11px 13px;border:1.5px solid var(--line);border-radius:10px;
background-color:var(--paper);color:var(--ink);font:inherit;font-size:1rem}
select{appearance:none;background-image:linear-gradient(45deg,transparent 50%,var(--mute) 50%),linear-gradient(135deg,var(--mute) 50%,transparent 50%);
background-position:calc(100% - 19px) 52%,calc(100% - 14px) 52%;background-size:5px 5px;background-repeat:no-repeat;padding-right:38px}
input:focus,textarea:focus,select:focus{outline:3px solid var(--chartreuse);outline-offset:1px;border-color:var(--cart)}
textarea{min-height:120px}
input[type=file]{font:inherit;font-size:.92rem;color:var(--mute);width:100%;padding:10px;border:1.5px dashed var(--line);border-radius:10px;background:var(--paper)}
input[type=file]::file-selector-button{font:inherit;font-weight:700;border:0;border-radius:8px;padding:8px 14px;margin-right:12px;cursor:pointer;background:var(--forest);color:#EEF3EC}
button,.btn{font:inherit;font-weight:700;border:0;border-radius:10px;padding:11px 18px;cursor:pointer;background:var(--cart);color:#fff;text-decoration:none;display:inline-block}
button:hover,.btn:hover{filter:brightness(1.08)}
button:focus-visible,.btn:focus-visible,a:focus-visible,summary:focus-visible{outline:3px solid var(--chartreuse);outline-offset:2px}
button.alt,.btn.alt{background:transparent;color:var(--cart);border:1.5px solid currentColor;padding:9.5px 16.5px}
button.del{background:transparent;color:var(--bad);border:1.5px solid currentColor;padding:9.5px 16.5px}
button.small,.btn.small{padding:6px 12px;font-size:.88rem}
.pick{display:flex;gap:10px}.pick select{flex:1}@media (max-width:560px){.pick{flex-direction:column}}

.mute{color:var(--mute);font-size:.94rem}.ok{color:var(--cart)}.warn{color:var(--warn)}.bad{color:var(--bad)}
.note{border-left:5px solid var(--cart);background:var(--paper);padding:11px 14px;margin:16px 0;border-radius:0 8px 8px 0}
.note.bad{border-left-color:var(--bad)}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}.row form{margin:0}
.card{background:var(--paper);border:1.5px solid var(--line);border-radius:14px;padding:20px;margin:16px 0}
.pill{display:inline-block;border-radius:99px;padding:1px 10px;font-size:.8rem;font-weight:700;background:var(--rec-bg);color:var(--cart)}

/* the bins: drawn like curbside carts, with a colored lid */
.bins{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;align-items:start}
@media (max-width:700px){.bins{grid-template-columns:1fr}}
.bin{position:relative;background:var(--paper);border:1.5px solid var(--line);border-top:0;border-radius:4px 4px 14px 14px;padding:18px 16px 14px;margin-top:14px}
.bin::before{content:"";position:absolute;left:-6px;right:-6px;top:-14px;height:16px;border-radius:9px 9px 3px 3px;background:var(--lid)}
.bin::after{content:"";position:absolute;left:50%;top:-20px;width:46px;height:8px;margin-left:-23px;border-radius:5px 5px 0 0;background:var(--lid)}
.bin.recycling{--lid:var(--leaf)}.bin.trash{--lid:var(--slate)}.bin.special{--lid:var(--chartreuse)}
.bin h3{margin:0 0 10px;font-size:1.3rem;font-weight:800;display:flex;justify-content:space-between;align-items:baseline}
.bt{display:flex;align-items:center;gap:8px}.bt svg{width:20px;height:20px;color:var(--lid)}
.bin.special .bt svg{color:#7A8400}
.count{font-family:var(--display);font-size:1.6rem;font-weight:800;color:var(--lid)}
.bin.special .count{color:#8C9700}
.bin ul{list-style:none;margin:0;padding:0}.bin li{padding:6px 0;border-top:1px dashed var(--line);font-size:.95rem;line-height:1.35}
.bin li:first-child{border-top:0}
.tag{display:inline-block;font-size:.72rem;font-weight:700;border-radius:4px;padding:1px 6px;margin-left:6px;vertical-align:1px;background:var(--forest);color:#C9DA3F}

/* tools: quiet rows, not cards */
.tools{margin-top:34px;border-top:2px solid var(--forest)}
.tool{display:flex;gap:14px;align-items:center;padding:18px 2px;border-bottom:1.5px solid var(--line);text-decoration:none;color:var(--ink);font-weight:inherit}
.tool h2{margin:0;font-size:1.15rem}.tool .mute{margin:2px 0 0}
.toolicon{width:40px;height:40px;flex:none;border-radius:9px;display:grid;place-items:center;background:var(--forest);color:#C9DA3F}
.toolicon svg{width:22px;height:22px}
a.tool:hover h2{text-decoration:underline;text-decoration-thickness:2px;text-underline-offset:4px}
details.tool{display:block;padding:0}
details.tool>summary{list-style:none;cursor:pointer;display:flex;gap:14px;align-items:center;padding:18px 2px}
details.tool>summary::-webkit-details-marker{display:none}
details.tool>summary::after{content:"+";margin-left:auto;font:700 1.5rem var(--display);color:var(--cart)}
details.tool[open]>summary::after{content:"\\2212"}
details.tool>div{padding:0 2px 22px 56px}@media (max-width:560px){details.tool>div{padding-left:2px}}
.scanlogo{width:40px;height:40px;flex:none}
.scanlogo .beam{animation:scan 2.6s ease-in-out infinite}
@keyframes scan{0%,100%{transform:translateY(-5px)}50%{transform:translateY(5px)}}
@media (prefers-reduced-motion:reduce){.scanlogo .beam{animation:none}}
.sumtext{display:flex;flex-direction:column}
/* EZscan flair */
.scanword{font-size:1.35rem !important;font-weight:800;letter-spacing:-.03em}
.scanword .ez{background:linear-gradient(115deg,var(--leaf) 10%,var(--chartreuse) 90%);-webkit-background-clip:text;background-clip:text;color:transparent;
padding-right:1px}
.ezscan .scanlogo{width:46px;height:46px;border-radius:11px;box-shadow:0 0 0 3px color-mix(in srgb,var(--chartreuse) 45%,transparent),0 6px 18px color-mix(in srgb,var(--leaf) 40%,transparent)}
.ezscan>summary{position:relative}
.ezscan[open]{background:linear-gradient(180deg,color-mix(in srgb,var(--chartreuse) 14%,transparent),transparent 220px);border-radius:0 0 14px 14px}
.ezscan[open]>summary::before{content:"";position:absolute;left:0;right:0;top:-1.5px;height:3px;background:linear-gradient(90deg,var(--leaf),var(--chartreuse))}
.ezscan button{background:linear-gradient(115deg,var(--leaf),var(--chartreuse));color:var(--forest);box-shadow:0 6px 16px color-mix(in srgb,var(--leaf) 30%,transparent)}
.ezscan input[type=file]{border-color:color-mix(in srgb,var(--leaf) 55%,var(--line));background:color-mix(in srgb,var(--chartreuse) 7%,var(--paper))}
.ezscan input[type=file]::file-selector-button{background:var(--forest);color:var(--chartreuse)}

/* saved rules */
.saved{margin-top:34px}.saved h2{font-size:1.2rem}
.list>div{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;align-items:center;padding:12px 0;border-top:1.5px solid var(--line)}

/* collapsible cards on other pages */
details.card{padding:0}details.card>summary{list-style:none;cursor:pointer;padding:16px 20px;font-weight:700;display:flex;align-items:center;gap:10px}
details.card>summary::-webkit-details-marker{display:none}
details.card>summary::after{content:"+";margin-left:auto;font:700 1.4rem var(--display);color:var(--cart)}details.card[open]>summary::after{content:"\\2212"}
details.card>summary .mute{font-weight:400}details.card>div{padding:0 20px 20px}

/* rule editor (tap) */
.group{margin:24px 0 4px;font:700 1.05rem var(--display);color:var(--forest)}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]) .group{color:#C9DA3F}}
:root[data-theme=dark] .group{color:#C9DA3F}
.item{display:grid;grid-template-columns:1fr auto auto;gap:12px;align-items:center;padding:12px 0;border-top:1px dashed var(--line)}
.group+.item{border-top:0}.item .name{font-weight:700}.item .sub{font-size:.85rem;color:var(--mute);margin-top:2px}
.seg{display:inline-flex;border:1.5px solid var(--line);border-radius:10px;overflow:hidden;background:var(--paper)}
.seg input{position:absolute;opacity:0;pointer-events:none}
.seg label{margin:0;padding:7px 12px;font-size:.88rem;font-weight:700;color:var(--mute);cursor:pointer;border-left:1.5px solid var(--line)}
.seg label:first-of-type{border-left:0}.seg input:focus-visible+label{outline:3px solid var(--chartreuse);outline-offset:-3px}
.seg input[value=recycling]:checked+label{background:var(--leaf);color:#fff}
.seg input[value=trash]:checked+label{background:var(--slate);color:#fff}
.seg input[value=special]:checked+label{background:var(--chartreuse);color:#13392B}
.tip select{width:auto;padding:7px 32px 7px 10px;font-size:.86rem}
.item:has(input[value=recycling]:checked) .tip{visibility:hidden}
@media (max-width:640px){.item{grid-template-columns:1fr;gap:8px}.seg{width:100%}.seg label{flex:1;text-align:center}.item:has(input[value=recycling]:checked) .tip{display:none}}
.savebar{position:sticky;bottom:0;background:var(--forest);color:#EEF3EC;margin:20px -16px -56px;padding:14px 16px;display:flex;gap:12px;align-items:center;justify-content:space-between;flex-wrap:wrap}
.savebar label{margin:0;font-weight:400;display:flex;gap:8px;align-items:center}.savebar button{background:var(--chartreuse);color:var(--forest)}
.back{color:var(--mute);text-decoration:none;font-weight:400;font-size:.92rem}

/* rule writer */
.writer{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(0,1fr);gap:16px;align-items:start}
@media (max-width:820px){.writer{grid-template-columns:1fr}}.writer .card{margin:0}
.editor{font:15px/1.75 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;min-height:300px;resize:vertical;background:var(--paper)}
.startrow{display:flex;gap:8px}.startrow input{flex:1}
.issues{margin:10px 0 0;padding:0;list-style:none}.issues li{font-size:.88rem;color:var(--bad);padding:2px 0}
.preview{position:sticky;top:12px}.preview .bins{grid-template-columns:1fr;gap:20px}
.preview .bin li.def{opacity:.55}.preview .bin li.def::after{content:" (not mentioned)";font-size:.75rem}
.help{font-size:.9rem}.help code{background:var(--sage);border:1px solid var(--line);border-radius:5px;padding:1px 6px}
.words{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.words button{background:var(--sage);color:var(--ink);border:1.5px solid var(--line);border-radius:99px;padding:3px 11px;font-size:.82rem;font-weight:400}
.opt{font-weight:400;color:var(--mute);font-size:.86rem}
table{width:100%;border-collapse:collapse}td,th{border-bottom:1px solid var(--line);padding:9px 6px;text-align:left;vertical-align:top}
</style></head><body>
<header><div class="bar"><a class="brand" href="/"><svg class="logo" viewBox="0 0 64 64" aria-hidden="true"><defs><clipPath id="c0C9"><path d="M12.60 23.0H51.40L47.55 50.0Q47.30 53.0 44.30 53.0H20.10Q17.10 53.0 16.85 50.0Z"/></clipPath></defs><rect width="64" height="64" rx="15" fill="#C9DA3F"/><path d="M27.5 13.6v-1.8c0-1 .8-1.8 1.8-1.8h5.4c1 0 1.8.8 1.8 1.8v1.8" fill="none" stroke="#13392B" stroke-width="2.6" stroke-linecap="round"/><rect x="9.5" y="13.5" width="45" height="5.6" rx="2.8" fill="#13392B"/><path d="M11.60 23.00 L31.40 23.00 L31.40 28.00 L12.27 28.00Z M14.93 48.00 L31.40 48.00 L31.40 54.00 L15.60 54.00Z M11.60 23.00 L18.00 23.00 L22.00 54.00 L15.60 54.00Z M14.60 35.50 L27.40 35.50 L27.40 40.50 L14.60 40.50Z M31.40 23.00 L52.40 23.00 L51.80 28.00 L31.40 28.00Z M31.40 48.00 L49.40 48.00 L48.80 54.00 L31.40 54.00Z M44.10 27.70 L51.80 27.70 L40.60 48.30 L33.30 48.30Z" fill="#13392B" clip-path="url(#c0C9)"/></svg><span class="word">EZtrash</span></a><button type="button" class="theme" id="theme" aria-label="Switch between light and dark mode" title="Light / dark mode"><svg class="moon" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/></svg><svg class="sun" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4" fill="none" stroke="currentColor" stroke-width="2"/><path d="M12 2.5v2M12 19.5v2M4.6 4.6 6 6M18 18l1.4 1.4M2.5 12h2M19.5 12h2M4.6 19.4 6 18M18 6l1.4-1.4" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg></button><script>(function(){var b=document.getElementById("theme"),r=document.documentElement;function dark(){return r.dataset.theme?r.dataset.theme==="dark":matchMedia("(prefers-color-scheme: dark)").matches;}function label(){b.setAttribute("aria-label",dark()?"Switch to light mode":"Switch to dark mode");}b.addEventListener("click",function(){var t=dark()?"light":"dark";r.dataset.theme=t;try{localStorage.setItem("eztrash-theme",t);}catch(e){}label();});label();})();</script></div></header>
<main>{{ content|safe }}</main></body></html>"""


def page(body, title, **ctx):
    """Render one screen (body) inside the shared page shell."""
    return render_template_string(SHELL, content=render_template_string(body, **ctx), title=title)


LOGIN = """<h1>Sign in to EZtrash</h1><div class="card"><form method="post">
<label for="code">Access code</label>
<input id="code" name="code" type="password" autocomplete="off" autofocus>
<p class="mute">The code is printed in the terminal where app.py is running.</p>
{% if error %}<p class="bad">{{ error }}</p>{% endif %}
<button>Sign in</button></form></div>"""

HOME = """{% if msg %}<div class="note">{{ msg }}</div>{% endif %}{% if err %}<div class="note bad">{{ err }}</div>{% endif %}
<section class="band" aria-label="Where the can is">
{% if city_picked %}<p class="label">Sorting for</p>
<div class="city">{{ active.city }}</div>
{% else %}<p class="label">No city selected</p>
<div class="city none">Select city</div>{% endif %}
<form method="post" action="{{ url_for('use_preset_form') }}"><input type="hidden" name="csrf" value="{{ csrf() }}">
<div class="pick"><select name="slug" aria-label="Select city" required>
<option value="" disabled selected hidden>Select city</option>
{% for state, cities in preset_groups %}<optgroup label="{{ state }}">
{% for slug, city in cities %}<option value="{{ slug }}">{{ city }}</option>{% endfor %}</optgroup>{% endfor %}
</select><button>Switch city</button></div></form>
<p class="hint">{% if own_rules %}The can is using your own rules, &ldquo;{{ own_rules }}&rdquo;. <a class="edit" href="{{ url_for('write', **{'from': 'active'}) }}">Edit them</a>.
{% elif city_picked %}<a class="edit" href="{{ url_for('write', **{'from': 'active'}) }}">Edit these rules</a>. You check every rule before the can uses it.
{% else %}Pick your city from the list. You check every rule before the can uses it.{% endif %}</p>
</section>

{% if active.city.startswith('(no') %}<div class="note bad">Until you select a city, everything goes to trash and hazardous items go to special.</div>{% endif %}
<div class="bins">
{% for b, label in [('recycling','Recycling'),('trash','Trash'),('special','Special')] %}
<div class="bin {{ b }}"><h3><span class="bt">{{ BIN_ICONS[b]|safe }}{{ label }}</span><span class="count" aria-label="{{ bins[b]|length }} items">{{ bins[b]|length }}</span></h3><ul>
{% for name, reason in bins[b] %}<li>{{ name }}{% if reason == 'dropoff' %}<span class="tag">drop-off</span>{% elif reason == 'hazardous' %}<span class="tag">hazardous</span>{% endif %}</li>
{% else %}<li class="mute">Nothing goes here.</li>{% endfor %}</ul></div>{% endfor %}
</div>
{% if cov and cov.unknown %}<div class="note bad">Your trained model has folders these rules don't know: {{ cov.unknown|join(', ') }}.
The can treats them as other trash. Rename those photo folders and train again.</div>{% endif %}

<div class="tools">
<a class="tool" href="{{ url_for('write') }}"><span class="toolicon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M4 20h4L19 9l-4-4L4 16v4zM13.5 6.5l4 4" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg></span>
<span><h2>Write your own rules</h2><span class="mute">For a school, or a town that isn't on the list. Type <em>recycling: cans, paper</em> and see it sort.</span></span></a>

<details class="tool ezscan"><summary><svg class="scanlogo" viewBox="0 0 40 40" aria-hidden="true"><rect width="40" height="40" rx="9" fill="#13392B"/><path d="M9.5 15v-3.2c0-1.3 1-2.3 2.3-2.3H15M25 9.5h3.2c1.3 0 2.3 1 2.3 2.3V15M30.5 25v3.2c0 1.3-1 2.3-2.3 2.3H25M15 30.5h-3.2c-1.3 0-2.3-1-2.3-2.3V25" fill="none" stroke="#C9DA3F" stroke-width="2.2" stroke-linecap="round"/><path d="M15.2 13h6.3l3.3 3.3v10c0 .5-.4.9-.9.9h-8.7c-.5 0-.9-.4-.9-.9V13.9c0-.5.4-.9.9-.9z" fill="#EEF3EC"/><path d="M21.5 13v3.3h3.3" fill="#B9D6C2"/><path d="M16.6 19.6h5.8M16.6 22h5.8M16.6 24.4h3.8" stroke="#7FAF8E" stroke-width="1.2" stroke-linecap="round"/><rect class="beam" x="11" y="19.4" width="18" height="2" rx="1" fill="#C9DA3F"/></svg><span class="sumtext"><h2 class="scanword"><span class="ez">EZ</span>scan</h2><span class="mute">Upload your city's rules as a PDF, Word, Markdown or text file.</span></span></summary><div>
<p class="mute" style="margin-top:0">The Pi reads the file itself, finds the items, and shows the sentence each rule came from.</p>
<form method="post" action="{{ url_for('analyze') }}" enctype="multipart/form-data">
<input type="hidden" name="csrf" value="{{ csrf() }}">
<label for="city">City or state</label><input id="city" name="city" type="text" placeholder="Marietta, GA" required>
<label for="file">Upload its rules (.pdf, .docx, .md, .txt)</label><input id="file" name="file" type="file" accept=".pdf,.docx,.md,.markdown,.txt">
<label for="text">or paste the text</label><textarea id="text" name="text" placeholder="Paste the city's 'what can I recycle' page here"></textarea>
<p class="mute">Scanned PDFs (pictures of text) can't be read. Paste the text instead.</p>
<p><button>Scan it</button></p></form></div></details>
</div>

<section class="saved"><h2>Saved rules</h2>
{% if not saved %}<p class="mute">Nothing saved yet. Switching city saves it here.</p>{% endif %}
<div class="list">{% for slug, rb in saved %}
<div><div><strong>{{ rb.city }}</strong> <span class="mute">{{ rb.created[:10] }}</span>
{% if rb.city == active.city %}<span class="pill ok">in use</span>{% endif %}</div>
<div class="row">
{% if rb.city != active.city %}<form method="post" action="{{ url_for('activate', slug=slug) }}"><input type="hidden" name="csrf" value="{{ csrf() }}"><button class="small">Use</button></form>{% endif %}
<a class="btn alt small" href="{{ url_for('write', **{'from': 's:' ~ slug}) }}">Edit</a>
<form method="post" action="{{ url_for('delete', slug=slug) }}" onsubmit="return confirm('Delete this rulebook?')"><input type="hidden" name="csrf" value="{{ csrf() }}"><button class="del small">Delete</button></form>
</div></div>{% endfor %}</div></section>"""

REVIEW = """<p style="margin:18px 0 0"><a class="back" href="{{ url_for('home') }}">&larr; Back without saving</a></p>
<h1>{{ rb.city }}</h1>
<p class="mute" style="margin-top:0">Tap where each item goes. {% if rb.source_name and rb.source_name != 'made by hand' %}Based on: {{ rb.source_name }}.{% endif %}</p>
{% for w in warnings %}<div class="note bad">{{ w }}</div>{% endfor %}
{% if n_default %}<div class="note bad">{{ n_default }} item(s) weren't covered by the document, so they use the safe default. Check them.</div>{% endif %}
{% if n_unverified %}<div class="note bad">{{ n_unverified }} answer(s) quote text that isn't in your document. Don't trust those rows.</div>{% endif %}
<form method="post"><input type="hidden" name="csrf" value="{{ csrf() }}">
<div class="card">
{% for gname, keys in groups %}<div class="group">{{ gname }}</div>
{% for key in keys %}{% set info = types[key] %}{% set r = rb.rules[key] %}
<div class="item"><div><div class="name">{{ info[0].split(' (')[0] }}</div>
{% if r.note %}<div class="sub">{{ r.note }}</div>{% endif %}
{% if from_doc %}{% if r.status == 'default' %}<div class="sub warn">Not in the document: safe default</div>
{% elif r.evidence and r.quote_verified %}<div class="sub">&ldquo;{{ r.evidence }}&rdquo;</div>
{% elif r.evidence %}<div class="sub bad">Quote not found: &ldquo;{{ r.evidence }}&rdquo;</div>{% endif %}{% endif %}</div>
<div class="seg" role="radiogroup" aria-label="Where {{ info[0] }} goes">
{% for b, lab in [('recycling','Recycling'),('trash','Trash'),('special','Special')] %}
<input type="radio" id="{{ key }}_{{ b }}" name="bin_{{ key }}" value="{{ b }}" {{ 'checked' if r.bin == b }}><label for="{{ key }}_{{ b }}">{{ lab }}</label>{% endfor %}
</div>
<div class="tip"><select name="reason_{{ key }}" aria-label="Tip shown for {{ info[0] }}">
<option value="" {{ 'selected' if r.reason == '' }}>No tip</option>
<option value="dropoff" {{ 'selected' if r.reason == 'dropoff' }}>Drop-off tip</option>
<option value="hazardous" {{ 'selected' if r.reason == 'hazardous' }}>Hazardous tip</option></select></div>
</div>{% endfor %}{% endfor %}
</div>

<details class="card"><summary>Name and phone numbers <span class="mute">optional</span></summary><div>
<label for="city">Name</label><input id="city" name="city" type="text" value="{{ rb.city }}">
<label for="cr">Recycling questions (phone or website)</label><input id="cr" name="contact_recycling" type="text" value="{{ rb.contacts.recycling }}">
<label for="ch">Hazardous waste (phone or website)</label><input id="ch" name="contact_hazardous" type="text" value="{{ rb.contacts.hazardous }}">
<p class="mute">These show on the can's screen with the drop-off and hazardous tips.</p></div></details>

<div class="savebar"><label><input type="checkbox" name="activate" value="1" checked> Use these rules on the can now</label>
<button>Save rules</button></div>
</form>"""


WRITE = r"""<p style="margin:18px 0 0"><a class="back" href="{{ url_for('home') }}">&larr; Back</a></p>
<h1>Write your rules</h1>
<p class="mute" style="margin-top:0">One line per bin. The preview updates as you type.</p>
{% if err %}<div class="note bad">{{ err }}</div>{% endif %}
<form method="post" id="wform"><input type="hidden" name="csrf" value="{{ csrf() }}">
<input type="hidden" name="source" id="source" value="{{ start.source }}">
<div class="writer">
<div class="card">
<label for="name">Name</label>
<input id="name" name="city" type="text" value="{{ start.name }}" placeholder="My school" required>
<label for="startfrom">Start from <span class="opt">(type a city, or pick from the list)</span></label>
<div class="startrow"><input id="startfrom" list="starts" type="text" placeholder="Blank, Austin, Marietta..." autocomplete="off">
<button type="button" class="alt" id="load">Load</button></div>
<datalist id="starts">{% for o in options %}<option value="{{ o.label }}">{% endfor %}</datalist>
<label for="rules">Rules</label>
<textarea id="rules" name="rules" class="editor" spellcheck="false">{{ start.text }}</textarea>
<ul class="issues" id="issues" aria-live="polite"></ul>
<details style="margin-top:12px"><summary class="mute" style="cursor:pointer">How to write rules</summary>
<div class="help"><p>Start each line with <code>recycling</code>, <code>trash</code> or <code>special</code>, then a colon, then the items.
Add <code>hazardous</code> or <code>drop-off</code> after special to choose the tip on the can's screen.
Anything you don't mention keeps the safe default. If an item is on two lines, the lower line wins.</p>
<p style="margin-bottom:4px">Words it knows (tap to add to the end):</p>
<div class="words">{% for k, w in text_names.items() %}<button type="button" data-w="{{ w }}">{{ w }}</button>{% endfor %}</div></div></details>
<details style="margin-top:10px"><summary class="mute" style="cursor:pointer">Phone numbers shown with tips (optional)</summary>
<label for="cr">Recycling questions</label><input id="cr" name="contact_recycling" type="text" value="{{ start.contacts.recycling }}">
<label for="ch">Hazardous waste</label><input id="ch" name="contact_hazardous" type="text" value="{{ start.contacts.hazardous }}"></details>
</div>
<div class="card preview"><h2>Preview</h2><div class="bins" id="bins"></div></div>
</div>
<div class="savebar"><label><input type="checkbox" name="activate" value="1" checked> Use these rules on the can now</label>
<button>Save rules</button></div>
</form>
<script>
var WORDS = {{ words|tojson }}, ITEMS = {{ items|tojson }}, OPTIONS = {{ options|tojson }};
var ta = document.getElementById('rules'), dirty = false;
function detectBin(t){ if(/special/.test(t))return 'special'; if(/recycl/.test(t))return 'recycling';
  if(/trash|landfill|garbage/.test(t))return 'trash'; if(/hazard|drop.?off|not collected|take to|bring to/.test(t))return 'special'; return null; }
function parse(text){
  var rules = {}, set = {}, issues = [];
  Object.keys(ITEMS).forEach(function(k){ rules[k] = {bin: ITEMS[k].bin, reason: ITEMS[k].reason}; });
  text.split('\n').forEach(function(raw){
    var line = raw.trim().replace(/^[-*• ]+/, '').trim(); if(!line) return;
    var low = line.toLowerCase(), m = /\s*(?::|->|=>|=|\s-\s|\s–\s)\s*/.exec(low);
    if(!m){ issues.push('Needs a colon, like "recycling: cans": ' + line); return; }
    var left = low.slice(0, m.index), right = low.slice(m.index + m[0].length), bin = null, items = '', rtext = '';
    [[right, left], [left, right]].some(function(p){ var b = detectBin(p[0]); if(b){ bin = b; items = p[1]; rtext = p[0]; } return !!b; });
    if(!bin){ issues.push('Say recycling, trash or special: ' + line); return; }
    var reason = '';
    if(bin === 'special') reason = /drop.?off|bring to|take to/.test(rtext) ? 'dropoff' : 'hazardous';
    else if(bin === 'trash' && /drop.?off/.test(rtext)) reason = 'dropoff';
    var keys = [];
    WORDS.forEach(function(w){ var re = new RegExp('\\b(?:' + w[0] + ')\\b');
      if(re.test(items)){ items = items.replace(new RegExp('\\b(?:' + w[0] + ')\\b', 'g'), ' ');
        w[1].forEach(function(k){ if(keys.indexOf(k) < 0) keys.push(k); }); } });
    var left_over = items.replace(/\b(and|or|the|all|any|of|with|for)\b/g, ' ').replace(/[,;.&]+/g, ' ').trim();
    if(left_over) issues.push('Not an item it knows: "' + left_over.replace(/\s+/g, ' ') + '"');
    keys.forEach(function(k){ rules[k] = {bin: bin, reason: reason}; set[k] = true; });
  });
  return {rules: rules, set: set, issues: issues};
}
function esc(s){ return s.replace(/[&<>"]/g, function(c){ return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }
function render(){
  var r = parse(ta.value), html = '';
  [['recycling','Recycling'],['trash','Trash'],['special','Special']].forEach(function(b){
    var li = '', n = 0;
    Object.keys(ITEMS).forEach(function(k){ var x = r.rules[k]; if(x.bin !== b[0]) return; n++;
      var tag = x.reason === 'dropoff' ? '<span class="tag">drop-off</span>' : x.reason === 'hazardous' ? '<span class="tag">hazardous</span>' : '';
      li += '<li class="' + (r.set[k] ? '' : 'def') + '">' + esc(ITEMS[k].name) + tag + '</li>'; });
    html += '<div class="bin ' + b[0] + '"><h3><span>' + b[1] + '</span><span>' + n + '</span></h3><ul>' + (li || '<li class="mute">nothing</li>') + '</ul></div>';
  });
  document.getElementById('bins').innerHTML = html;
  document.getElementById('issues').innerHTML = r.issues.map(function(i){ return '<li>' + esc(i) + '</li>'; }).join('');
}
ta.addEventListener('input', function(){ dirty = true; render(); });
document.getElementById('load').addEventListener('click', function(){
  var v = document.getElementById('startfrom').value.trim().toLowerCase();
  var o = OPTIONS.find(function(o){ return o.label.toLowerCase() === v; }) ||
          OPTIONS.find(function(o){ return v && o.label.toLowerCase().indexOf(v) >= 0; });
  if(!o){ alert('No match. Try a city name like "Austin", or "Blank".'); return; }
  if(dirty && !confirm('Replace what you typed with ' + o.label + '?')) return;
  ta.value = o.text; if(o.name) document.getElementById('name').value = o.name;
  document.getElementById('source').value = o.source;
  document.getElementById('cr').value = o.contacts.recycling || ''; document.getElementById('ch').value = o.contacts.hazardous || '';
  document.getElementById('startfrom').value = o.label; dirty = false; render();
});
document.getElementById('startfrom').addEventListener('keydown', function(e){ if(e.key === 'Enter'){ e.preventDefault(); document.getElementById('load').click(); } });
document.querySelectorAll('.words button').forEach(function(b){ b.addEventListener('click', function(){
  var lines = ta.value.replace(/\s+$/, '').split('\n'), last = lines[lines.length - 1] || '';
  lines[lines.length - 1] = /:\s*$/.test(last) ? last + ' ' + b.dataset.w : (last.indexOf(':') >= 0 ? last + ', ' + b.dataset.w : last + b.dataset.w);
  ta.value = lines.join('\n'); dirty = true; render(); ta.focus(); }); });
render();
</script>"""


def _local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


if __name__ == "__main__":
    import logging
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--local-only", action="store_true", help="only this computer can open the app")
    a = ap.parse_args()
    host = "127.0.0.1" if a.local_only else "0.0.0.0"
    logging.getLogger("werkzeug").setLevel(logging.ERROR)   # no line per page view
    import flask.cli
    flask.cli.show_server_banner = lambda *args, **kwargs: None
    public = os.environ.get("SORTER_PUBLIC_URL", "")
    rows = [("On this computer", f"http://localhost:{a.port}")]
    if not a.local_only:
        rows.append(("On your Wi-Fi", f"http://{_local_ip()}:{a.port}"))
    if public:
        rows.append(("Public link", public))
    rows.append(("Access code", ACCESS_CODE))
    width = max(len(k) for k, _ in rows)
    color = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
    def c(code, text):
        return f"\033[{code}m{text}\033[0m" if color else text
    CH, LEAF, MINT, WHITE = "38;2;201;218;63", "38;2;52;165;99", "38;2;150;190;165", "38;2;238;243;236"
    rule = c(LEAF, "  " + "━" * (width + 3 + max(len(v) for _, v in rows)))
    print()
    print("  " + c("1;" + CH, "EZ") + c("1;" + WHITE, "trash") + c(MINT, " is running"))
    print(rule)
    for k, v in rows:
        val = c("1;" + CH, v) if k == "Access code" else c("1;" + WHITE, v)
        print(f"  {c(MINT, k.ljust(width))}   {val}")
    print(rule)
    stop = "Press Esc to stop." if os.environ.get("EZTRASH_LAUNCHER") else "Press Ctrl+C to stop."
    print("  " + c(MINT, "Open one of the addresses in a browser. " + stop) + "\n", flush=True)
    app.run(host=host, port=a.port, debug=False)
