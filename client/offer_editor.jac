"""Offer editing with unchanged validation, draft callbacks and submit guards."""
import from .ui { ui, formStack, formInput, formSecondary, formHint }
import type from ..services.promo { ActionResult }

glob editorRow = {"display": "grid", "gridTemplateColumns": "repeat(auto-fit,minmax(min(100%,180px),1fr))", "gap": 12};

def validateOfferDraft(draft: dict[str, str]) -> str {
    moneyPattern = new(RegExp, "^[0-9]+([.][0-9]{1,2})?$");
    if not draft["title"].strip() { return "Add an offer title so customers know what they get."; }
    if not moneyPattern.test(draft["price"]) or float(draft["price"]) > 9999.99 {
        return "Enter an offer price from 0 to 9999.99 with at most two decimal places.";
    }
    if draft["regular_price"] and (not moneyPattern.test(draft["regular_price"]) or float(draft["regular_price"]) > 9999.99 or float(draft["regular_price"]) < float(draft["price"])) {
        return "Regular price must be at least the offer price, with at most two decimal places.";
    }
    if not draft["start_local"] or not draft["end_local"] or draft["end_local"] <= draft["start_local"] {
        return "Choose an end time after the start time. Times are local to Ann Arbor.";
    }
    if not new(RegExp, "^[0-9]+$").test(draft["quantity"]) or int(draft["quantity"]) < 1 or int(draft["quantity"]) > 10000 {
        return "Quantity must be a whole number from 1 to 10000.";
    }
    if not draft["eligibility"].strip() or not draft["terms"].strip() {
        return "Add eligibility and terms so customers know how to use this offer.";
    }
    for raw in draft["dietary"].split(",") {
        value = raw.strip().lower();
        if value and value not in ["vegetarian", "vegan", "gluten-free", "halal"] {
            return "Use only these dietary tags: vegetarian, vegan, gluten-free, halal.";
        }
    }
    return "";
}

def:pub OfferEditor(initial: dict[str, str], draftOwner: str, onDraftChange: Callable[[dict[str, str]], None],
    onBusyChange: Callable[[bool], None],
    saveOffer: Callable[[str, str, str, str, str, str, str, str, str, str, str, str, str], ActionResult],
    onSaved: Callable[[str], None], onCancel: Callable[[], None]) -> JsxElement {
    draft = {**initial, "start_local": initial["start_local"].replace(" ", "T", 1), "end_local": initial["end_local"].replace(" ", "T", 1)};
    has busy: bool = False,
        message: str = "",
        mounted: Ref[bool] = Ref(True),
        inFlight: Ref[bool] = Ref(False),
        createKey: Ref[str] = Ref(""),
        recovered: bool = False,
        errorRef: Ref[HTMLElement] = Ref();
    storageKey = "mlocal_offer_draft_" + draftOwner;
    can with entry {
        mounted.current = True;
        if not initial["offer_id"] and draftOwner {
            try {
                raw = localStorage.getItem(storageKey);
                if raw {
                    if len(raw) > 12000 { raise Exception("Invalid draft"); }
                    saved = JSON.parse(raw) as dict[str, any];
                    restored = saved["draft"] as dict[str, str];
                    updated = {**draft};
                    for key in draft {
                        if not isinstance(restored.get(key), str) or len(restored[key]) > 2000 { raise Exception("Invalid draft"); }
                        updated[key] = restored[key];
                    }
                    if updated["offer_id"] { raise Exception("Invalid draft"); }
                    keyValue = saved["create_key"];
                    if not isinstance(keyValue, str) or len(keyValue) > 80 { raise Exception("Invalid draft"); }
                    createKey.current = keyValue;
                    onDraftChange(updated);
                    recovered = True;
                }
            } except Exception { message = "Could not read the draft saved on this device. Cancel to discard it."; }
        }
    }
    can with exit { mounted.current = False; }

    def keepDraft(updated: dict[str, str]) -> bool {
        if draft["offer_id"] { return True; }
        try {
            if not draftOwner { raise Exception("Missing owner"); }
            localStorage.setItem(storageKey, JSON.stringify({"draft": updated, "create_key": createKey.current or ""}));
            return True;
        } except Exception {
            showError("Could not keep this draft on your device. Allow site storage, then try again.");
            return False;
        }
    }
    def clearDraft() {
        if not draft["offer_id"] and draftOwner {
            try { localStorage.removeItem(storageKey); } except Exception {}
        }
    }

    def field(key: str, value: str) {
        updated = {**draft};
        updated[key] = value;
        onDraftChange(updated);
        keepDraft(updated);
    }
    def toggleDiet(key: str) {
        picked = [x.strip() for x in draft["dietary"].split(",") if x.strip()];
        field("dietary", ", ".join([x for x in picked if x != key] if key in picked else picked + [key]));
    }
    def showError(text: str) {
        message = text;
        requestAnimationFrame(lambda { if errorRef.current { errorRef.current.focus(); } });
    }
    async def submit(event: FormEvent) {
        event.preventDefault();
        if inFlight.current { return; }
        invalid = validateOfferDraft(draft);
        if invalid { showError(invalid); return; }
        inFlight.current = True;
        busy = True;
        onBusyChange(True);
        message = "";
        try {
            if not draft["offer_id"] and not createKey.current { createKey.current = (crypto as any).randomUUID(); }
            if not keepDraft(draft) { return; }
            reply = await saveOffer(draft["offer_id"], draft["title"].strip(), draft["description"].strip(), draft["price"], draft["regular_price"], draft["start_local"], draft["end_local"], draft["quantity"], draft["eligibility"].strip(), draft["terms"].strip(), draft["dietary"], draft["menu_item"].strip(), createKey.current or "");
            if not mounted.current { return; }
            if not reply.ok { showError(reply.message or "The offer could not be saved."); return; }
            clearDraft();
            await onSaved(reply.message or "Offer saved.");
        } except Exception {
            if mounted.current { showError("Could not save the offer. Your entries are kept; check the connection and retry."); }
        } finally {
            inFlight.current = False;
            if mounted.current { busy = False; onBusyChange(False); }
        }
    }
    def textField(key: str, title: str, placeholder: str, maxLength: int, options: dict[str, any] = {}) -> JsxElement {
        return <label style={{**formStack, "gap": 6, "fontSize": 14, "fontWeight": 600}}>{title}<input style={formInput} placeholder={placeholder} maxLength={maxLength} value={draft[key]} disabled={busy} onChange={lambda (event: ChangeEvent) { field(key, event.target.value); }} {**options}/></label>;
    }
    def multiField(key: str, title: str, placeholder: str) -> JsxElement {
        return <label style={{**formStack, "gap": 6, "fontSize": 14, "fontWeight": 600}}>{title}<textarea style={{**formInput, "minHeight": 88, "resize": "vertical"}} placeholder={placeholder} maxLength={2000} value={draft[key]} disabled={busy} onChange={lambda (event: ChangeEvent) { field(key, event.target.value); }}/></label>;
    }
    return <form aria-label={"Edit offer" if draft["offer_id"] else "New offer"} style={formStack} onSubmit={submit} noValidate>
        <h3 style={{"fontSize": 20, "margin": 0}}>{"Edit offer" if draft["offer_id"] else "New offer"}</h3>
        <p style={formHint}>{"Saving updates future claims. Existing claims keep their promised price, terms and expiry. Paused offers stay paused." if draft["offer_id"] else "Your offer appears publicly when you publish. A future start time schedules it. Your draft is kept on this device; Cancel discards it."}</p>
        {if recovered { <p role="status" style={formHint}>Recovered your draft from this device.</p> }}
        {textField("title", "Title *", "Lunch bowl for $7", 120, {"required": True, "autoFocus": True})}
        {multiField("description", "Description", "What the student gets")}
        <div style={editorRow}>{textField("price", "Offer price ($) *", "7.00", 10, {"inputMode": "decimal", "required": True})}{textField("regular_price", "Regular price ($), optional", "11.50", 10, {"inputMode": "decimal"})}</div>
        <p style={formHint}>Prices exclude tax unless your terms say otherwise. No payment is collected here.</p>
        <div style={editorRow}>{textField("start_local", "Starts (Eastern) *", "2026-09-26 11:00", 30, {"type": "datetime-local", "required": True})}{textField("end_local", "Ends (Eastern) *", "2026-09-26 14:00", 30, {"type": "datetime-local", "required": True})}</div>
        <p style={formHint}>Times are Ann Arbor local time (Eastern), even when you are traveling.</p>
        {textField("quantity", "Quantity *", "10", 5, {"inputMode": "numeric", "required": True})}
        {textField("eligibility", "Eligibility *", "Students with a valid ID", 300, {"required": True})}
        {multiField("terms", "Terms *", "One per student. Dine-in only.")}
        <details>
            <summary>More details (optional)</summary>
            <div style={formStack}>
                {textField("menu_item", "Menu item", "Veggie Dan Dan Noodles", 120)}
                <fieldset style={{"border": 0, "padding": 0, "margin": 0, "minWidth": 0}}>
                    <legend style={{"fontSize": 14, "fontWeight": 600, "marginBottom": 8}}>Dietary options</legend>
                    <div style={{"display": "flex", "flexWrap": "wrap", "gap": 12}}>
                        {[<label key={diet} style={{"display": "flex", "alignItems": "center", "gap": 8, "minHeight": 44}}><input type="checkbox" aria-label={diet.capitalize()} checked={diet in [x.strip() for x in draft["dietary"].split(",")]} disabled={busy} onChange={lambda { toggleDiet(diet); }} style={{"width": 20, "height": 20}}/>{diet.capitalize()}</label> for diet in ["vegetarian", "vegan", "gluten-free", "halal"]]}
                    </div>
                    <p style={formHint}>Select only the options this offer meets.</p>
                </fieldset>
            </div>
        </details>
        {if message { <p ref={errorRef} tabIndex={-1} role="alert" style={{**formHint, "color": ui.bad}}>{message}</p> }}
        <div style={{"display": "flex", "gap": 8, "flexWrap": "wrap"}}>
            <button style={{**formSecondary, "flex": "1 1 180px", "background": ui.navy, "borderColor": ui.navy, "color": ui.accentText}} disabled={busy}>{"Saving..." if busy else "Save changes" if draft["offer_id"] else "Publish offer"}</button>
            <button style={{**formSecondary, "flex": "1 1 120px"}} disabled={busy} type="button" onClick={lambda { clearDraft(); onCancel(); }}>Cancel</button>
        </div>
    </form>;
}
