"""PromoPusher - time-limited Ann Arbor restaurant offers for students.

Server rules live in services/promo.jac; the whole mobui UI lives here
(E1105 no-HTML guard is only enforced on the entry module).
"""

# Server context: plain import registers every endpoint in-process.
import from services.promo {
    list_offers,
    get_offer,
    claim_offer,
    merchant_portal,
    update_profile,
    save_offer,
    set_offer_status,
    redeem_code,
    offer_defaults,
    OfferView,
    MerchantView,
    ActionResult,
    ClaimView
}

import from "@jac/mobui" {
    View,
    Text,
    Pressable,
    TextInput,
    ScrollView,
    useWindowDimensions
}
import from .theme { C, buildStyles, statusColors, money }


glob styles = buildStyles(C);

glob DIETS: list[str] = ["vegetarian", "vegan", "gluten-free", "halal"];

glob WINDOWS: list[list[str]] = [["any", "Any time"], ["now", "Right now"], ["today", "Today"]];

glob BUDGETS: list[str] = ["", "5", "8", "10"];

glob MERCHANTS: list[list[str]] = [
    ["noodle-demo", "Noodle Lab"],
    ["leaf-demo", "Arbor Leaf"],
    ["dough-demo", "Diag Dough"]
];


def Chip(label: str, on: bool, onPress: any) -> JsxElement {
    return <Pressable style={[styles.chip, styles.chipOn if on else {}]} onPress={onPress}>
        <Text style={[styles.chipText, styles.chipTextOn if on else {}]}>{label}</Text>
    </Pressable>;
}


def StatusPill(state: str) -> JsxElement {
    cols = statusColors(state);
    return <View style={[styles.status, {"backgroundColor": cols[0]}]}>
        <Text style={[styles.statusText, {"color": cols[1]}]}>{state.upper()}</Text>
    </View>;
}


def DemoTag() -> JsxElement {
    return <View style={styles.demo}><Text style={styles.demoText}>DEMO</Text></View>;
}


def Message(text: str, good: bool) -> JsxElement {
    if not text {
        return <View />;
    }
    return <View style={styles.msgGood if good else styles.msgBad}>
        <Text style={styles.msgGoodText if good else styles.msgBadText}>{text}</Text>
    </View>;
}


def Field(
    label: str, value: str, onChange: any, placeholder: str, multiline: bool
) -> JsxElement {
    return <View style={[styles.field, styles.flex1]}>
        <Text style={styles.label}>{label}</Text>
        <TextInput
            style={[styles.input, styles.inputMulti if multiline else {}]}
            value={value}
            placeholder={placeholder}
            placeholderTextColor={C["muted"]}
            multiline={multiline}
            onChangeText={onChange}
        />
    </View>;
}


def OfferCard(o: OfferView, onOpen: any) -> JsxElement {
    saving = o.regular_price - o.price;
    live = o.state == "active";
    status = (
        ("Your code " + o.my_code) if o.my_code and o.my_status == "claimed"
        else o.time_label + "  ·  " + str(o.remaining) + " left" if live
        else o.time_label if o.state == "scheduled" else o.state.capitalize()
    );
    return <Pressable style={[styles.card, {} if live else styles.cardMuted]} onPress={onOpen}>
        <View style={styles.rowBetween}>
            <Text style={styles.restaurant}>{o.restaurant.replace(" (Demo)", "")}</Text>
            {(<DemoTag />) if o.is_demo else <View />}
        </View>
        <Text style={styles.offerTitle}>{o.title}</Text>
        <View style={styles.rowBetween}>
            <View style={styles.row}>
                <Text style={styles.price}>{money(o.price)}</Text>
                {(<Text style={styles.strike}>{money(o.regular_price)}</Text>) if saving > 0 else <View />}
            </View>
            {(
                <View style={styles.badge}>
                    <Text style={styles.badgeText}>{"Save " + money(saving)}</Text>
                </View>
            ) if saving > 0 else <View />}
        </View>
        <Text style={[styles.small, {"color": C["accent"], "fontWeight": "700"} if o.my_code else {}]}>{status}</Text>
    </Pressable>;
}


def:pub app -> JsxElement {
    has tab: str = "discover",
        student: str = "demo-student",
        maxPrice: str = "",
        timeWin: str = "any",
        diets: list[str] = [],
        offers: list[OfferView] = [],
        loading: bool = True,
        loadError: str = "",
        selected: str = "",
        detail: OfferView | None = None,
        detailLoading: bool = False,
        claimMsg: str = "",
        claimOk: bool = False,
        busy: bool = False,
        mKey: str = "",
        portal: MerchantView | None = None,
        mLoading: bool = False,
        mMsg: str = "",
        mOk: bool = True,
        pName: str = "",
        pCuisine: str = "",
        pBlurb: str = "",
        pAddress: str = "",
        pHood: str = "",
        pNote: str = "",
        pNoteDate: str = "",
        editing: bool = False,
        eId: str = "",
        eTitle: str = "",
        eDesc: str = "",
        ePrice: str = "",
        eRegular: str = "",
        eStart: str = "",
        eEnd: str = "",
        eQty: str = "",
        eElig: str = "",
        eTerms: str = "",
        eDiets: str = "",
        eItem: str = "",
        eMsg: str = "",
        code: str = "",
        rMsg: str = "",
        rOk: bool = False;

    viewport = useWindowDimensions();

    async def loadOffers(price: str, win: str, ds: list[str]) {
        loading = True;
        loadError = "";
        try {
            offers = await list_offers(student, price, win, ",".join(ds));
        } except Exception as e {
            loadError = "Could not load offers. " + str(e);
        }
        loading = False;
    }

    async can with entry {
        await loadOffers("", "any", []);
    }

    async def refresh() {
        await loadOffers(maxPrice, timeWin, diets);
    }

    def pickBudget(v: str) {
        maxPrice = v;
        loadOffers(v, timeWin, diets);
    }

    def pickWindow(v: str) {
        timeWin = v;
        loadOffers(maxPrice, v, diets);
    }

    def toggleDiet(d: str) {
        nxt = [x for x in diets if x != d] if d in diets else diets + [d];
        diets = nxt;
        loadOffers(maxPrice, timeWin, nxt);
    }

    async def openOffer(oid: str) {
        selected = oid;
        claimMsg = "";
        detailLoading = True;
        detail = await get_offer(oid, student, maxPrice, timeWin, ",".join(diets));
        detailLoading = False;
    }

    async def claim() {
        if busy or not selected {
            return;
        }
        busy = True;
        res = await claim_offer(selected, student);
        claimOk = res.ok;
        claimMsg = res.message;
        detail = await get_offer(selected, student, maxPrice, timeWin, ",".join(diets));
        busy = False;
        refresh();
    }

    def fillProfile(p: MerchantView) {
        pName = p.name;
        pCuisine = p.cuisine;
        pBlurb = p.blurb;
        pAddress = p.address;
        pHood = p.neighborhood;
        pNote = p.entrance_note;
        pNoteDate = p.note_date;
    }

    async def openMerchant(k: str) {
        mKey = k;
        mMsg = "";
        editing = False;
        mLoading = True;
        p = await merchant_portal(k);
        portal = p if p.ok else None;
        if p.ok {
            fillProfile(p);
        } else {
            mOk = False;
            mMsg = p.message;
        }
        mLoading = False;
    }

    async def reloadPortal() {
        p = await merchant_portal(mKey);
        portal = p if p.ok else None;
    }

    async def saveProfile() {
        busy = True;
        p = await update_profile(mKey, pName, pCuisine, pBlurb, pAddress, pHood, pNote, pNoteDate);
        mOk = p.message == "Profile saved.";
        mMsg = p.message;
        if p.ok {
            portal = p;
        }
        busy = False;
        refresh();
    }

    async def newOffer() {
        d = await offer_defaults();
        eId = "";
        eTitle = "";
        eDesc = "";
        ePrice = "";
        eRegular = "";
        eStart = d[0];
        eEnd = d[1];
        eQty = "10";
        eElig = "Students with a valid university ID";
        eTerms = "";
        eDiets = "";
        eItem = "";
        eMsg = "";
        editing = True;
    }

    def editOffer(o: OfferView) {
        eId = o.id;
        eTitle = o.title;
        eDesc = o.description;
        ePrice = str(o.price);
        eRegular = str(o.regular_price);
        eStart = o.start_input;
        eEnd = o.end_input;
        eQty = str(o.quantity);
        eElig = o.eligibility;
        eTerms = o.terms;
        eDiets = ", ".join(o.dietary);
        eItem = o.menu_item;
        eMsg = "";
        editing = True;
    }

    async def submitOffer() {
        busy = True;
        res = await save_offer(
            mKey, eId, eTitle, eDesc, ePrice, eRegular, eStart, eEnd, eQty, eElig, eTerms, eDiets, eItem
        );
        busy = False;
        if res.ok {
            editing = False;
            mOk = True;
            mMsg = res.message;
            await reloadPortal();
            refresh();
        } else {
            eMsg = res.message;
        }
    }

    async def toggleStatus(o: OfferView) {
        res = await set_offer_status(mKey, o.id, "active" if o.state == "paused" else "paused");
        mOk = res.ok;
        mMsg = res.message;
        await reloadPortal();
        refresh();
    }

    async def redeem() {
        if busy {
            return;
        }
        busy = True;
        res = await redeem_code(mKey, code);
        rOk = res.ok;
        rMsg = res.message;
        if res.ok {
            code = "";
        }
        await reloadPortal();
        busy = False;
        refresh();
    }

    def goTab(t: str) {
        tab = t;
        selected = "";
        detail = None;
    }

    # ---------------------------------------------------------- screens ---

    def MerchantPicker() -> JsxElement {
        return <View style={styles.section}>
            <Text style={styles.h2}>Sign in as a demo merchant</Text>
            <Text style={styles.small}>
                Each restaurant has its own merchant key. You only see and change your own offers and claims.
            </Text>
            <View style={styles.wrap}>
                {[
                    <Chip key={m[0]} label={m[1]} on={mKey == m[0]} onPress={lambda { openMerchant(m[0]); }} />
                    for m in MERCHANTS
                ]}
            </View>
            <View style={styles.row}>
                <View style={styles.flex1}>
                    <TextInput
                        style={styles.input}
                        value={mKey}
                        placeholder="Merchant key"
                        placeholderTextColor={C["muted"]}
                        autoCapitalize="none"
                        onChangeText={lambda (t: str) { mKey = t; }}
                    />
                </View>
                <Pressable style={styles.btnGhost} onPress={lambda { openMerchant(mKey); }}>
                    <Text style={styles.btnGhostText}>Open</Text>
                </Pressable>
            </View>
            {(<Message text={mMsg} good={mOk} />) if portal is None else <View />}
        </View>;
    }

    def Discover() -> JsxElement {
        return <View style={styles.content}>
            <View style={styles.header}>
                <Text style={styles.brand}>PROMOPUSHER · ANN ARBOR</Text>
                <Text style={styles.title}>Hungry? Here is what is good nearby.</Text>
            </View>
            <View style={styles.row}>
                <Text style={styles.small}>Claiming as</Text>
                <View style={styles.flex1}>
                    <TextInput
                        style={[styles.input, {"paddingVertical": 8}]}
                        value={student}
                        placeholder="Your name or student ID"
                        placeholderTextColor={C["muted"]}
                        autoCapitalize="none"
                        onChangeText={lambda (t: str) { student = t; }}
                        onBlur={lambda { refresh(); }}
                    />
                </View>
            </View>
            <ScrollView horizontal={True} showsHorizontalScrollIndicator={False} contentContainerStyle={styles.row}>
                {[
                    <Chip key={"b" + b} label={"Any price" if b == "" else "Under $" + b} on={maxPrice == b} onPress={lambda { pickBudget(b); }} />
                    for b in BUDGETS
                ]}
            </ScrollView>
            <ScrollView horizontal={True} showsHorizontalScrollIndicator={False} contentContainerStyle={styles.row}>
                {[
                    <Chip key={w[0]} label={w[1]} on={timeWin == w[0]} onPress={lambda { pickWindow(w[0]); }} />
                    for w in WINDOWS
                ]}
                {[
                    <Chip key={d} label={d.capitalize()} on={d in diets} onPress={lambda { toggleDiet(d); }} />
                    for d in DIETS
                ]}
            </ScrollView>
            {(
                <View style={styles.empty}><Text style={styles.subtitle}>Finding deals...</Text></View>
            ) if loading else (
                <View style={styles.msgBad}><Text style={styles.msgBadText}>{loadError}</Text></View>
            ) if loadError else (
                <View style={styles.empty}>
                    <Text style={styles.h2}>Nothing matches yet</Text>
                    <Text style={styles.small}>Try removing a filter.</Text>
                </View>
            ) if not offers else <View style={{"gap": 12}}>
                {[<OfferCard key={o.id} o={o} onOpen={lambda { openOffer(o.id); }} /> for o in offers]}
            </View>}
        </View>;
    }

    def Detail() -> JsxElement {
        if detailLoading or detail is None {
            return <View style={styles.content}>
                <View style={styles.empty}>
                    <Text style={styles.subtitle}>{"Loading offer..." if detailLoading else "Offer not found."}</Text>
                </View>
            </View>;
        }
        o = detail;
        claimable = o.state == "active" and o.my_status == "";
        saving = o.regular_price - o.price;
        return <View style={styles.content}>
            <Pressable onPress={lambda { selected = ""; detail = None; }}>
                <Text style={styles.link}>Back to offers</Text>
            </Pressable>
            <View style={styles.header}>
                <View style={styles.row}>
                    <Text style={styles.restaurant}>{o.restaurant.replace(" (Demo)", "")}</Text>
                    {(<DemoTag />) if o.is_demo else <View />}
                </View>
                <Text style={styles.title}>{o.title}</Text>
                <Text style={styles.subtitle}>{o.description}</Text>
            </View>
            <View style={styles.row}>
                <Text style={styles.priceBig}>{money(o.price)}</Text>
                {(<Text style={styles.strike}>{money(o.regular_price)}</Text>) if saving > 0 else <View />}
                {(
                    <View style={styles.badge}><Text style={styles.badgeText}>{"Save " + money(saving)}</Text></View>
                ) if saving > 0 else <View />}
            </View>
            <View style={styles.row}>
                <StatusPill state={o.state} />
                <Text style={styles.small}>
                    {o.time_label + ("  ·  " + str(o.remaining) + " left" if o.state == "active" else "")}
                </Text>
            </View>
            {(
                <View style={styles.wrap}>
                    {[
                        <View key={r} style={[styles.tag, {"backgroundColor": C["goodSoft"] if not r.startswith("Not") and not r.startswith("Over") else C["badSoft"]}]}>
                            <Text style={[styles.tagText, {"color": C["good"] if not r.startswith("Not") and not r.startswith("Over") else C["bad"]}]}>{r}</Text>
                        </View>
                        for r in o.reasons
                    ]}
                </View>
            ) if o.reasons else <View />}
            {(
                <View style={styles.codeBox}>
                    <Text style={styles.codeSub}>{"SHOW THIS CODE AT THE COUNTER" if o.my_status == "claimed" else "REDEEMED"}</Text>
                    <Text style={styles.codeText}>{o.my_code}</Text>
                    <Text style={styles.codeSub}>
                        {"Hold expires " + o.my_expires + ". Unused claims release automatically." if o.my_status == "claimed" else "Enjoy your meal."}
                    </Text>
                </View>
            ) if o.my_code else <View />}
            <Message text={claimMsg} good={claimOk} />
            <Pressable
                style={[styles.btn, {} if claimable else styles.btnDisabled]}
                disabled={not claimable or busy}
                onPress={lambda { claim(); }}
            >
                <Text style={styles.btnText}>
                    {"Claiming..." if busy else "Claim this offer" if claimable else "Already claimed" if o.my_status else "Not claimable right now"}
                </Text>
            </Pressable>
            {(
                <View style={styles.note}>
                    <Text style={[styles.noteText, {"fontWeight": "800"}]}>{"Getting in" + (" · updated " + o.note_date if o.note_date else "")}</Text>
                    <Text style={styles.noteText}>{o.entrance_note}</Text>
                </View>
            ) if o.entrance_note else <View />}
            <View style={styles.section}>
                <Text style={styles.body}>{o.address + (" · " + o.neighborhood if o.neighborhood else "")}</Text>
                <View style={styles.divider} />
                <Text style={styles.small}>{"For: " + o.eligibility}</Text>
                <Text style={styles.small}>{o.terms or "No additional terms."}</Text>
            </View>
        </View>;
    }

    def Editor() -> JsxElement {
        return <View style={styles.section}>
            <Text style={styles.h2}>{"Edit offer" if eId else "New offer"}</Text>
            <Field label="Title" value={eTitle} onChange={lambda (t: str) { eTitle = t; }} placeholder="Lunch bowl for $7" multiline={False} />
            <Field label="Description" value={eDesc} onChange={lambda (t: str) { eDesc = t; }} placeholder="What the student gets" multiline={True} />
            <View style={styles.fieldRow}>
                <Field label="Offer price" value={ePrice} onChange={lambda (t: str) { ePrice = t; }} placeholder="7.00" multiline={False} />
                <Field label="Regular price" value={eRegular} onChange={lambda (t: str) { eRegular = t; }} placeholder="11.50" multiline={False} />
            </View>
            <View style={styles.fieldRow}>
                <Field label="Starts" value={eStart} onChange={lambda (t: str) { eStart = t; }} placeholder="2026-09-26 11:00" multiline={False} />
                <Field label="Ends" value={eEnd} onChange={lambda (t: str) { eEnd = t; }} placeholder="2026-09-26 14:00" multiline={False} />
            </View>
            <Text style={styles.small}>Times are Ann Arbor local time, format YYYY-MM-DD HH:MM.</Text>
            <View style={styles.fieldRow}>
                <Field label="Quantity" value={eQty} onChange={lambda (t: str) { eQty = t; }} placeholder="10" multiline={False} />
                <Field label="Menu item" value={eItem} onChange={lambda (t: str) { eItem = t; }} placeholder="Veggie Dan Dan Noodles" multiline={False} />
            </View>
            <Field label="Eligibility" value={eElig} onChange={lambda (t: str) { eElig = t; }} placeholder="Students with a valid ID" multiline={False} />
            <Field label="Terms" value={eTerms} onChange={lambda (t: str) { eTerms = t; }} placeholder="One per student. Dine-in only." multiline={True} />
            <Field label="Dietary tags" value={eDiets} onChange={lambda (t: str) { eDiets = t; }} placeholder="vegetarian, vegan, gluten-free, halal" multiline={False} />
            <Message text={eMsg} good={False} />
            <View style={styles.row}>
                <Pressable style={[styles.btn, styles.flex1]} disabled={busy} onPress={lambda { submitOffer(); }}>
                    <Text style={styles.btnText}>{"Saving..." if busy else "Save offer"}</Text>
                </Pressable>
                <Pressable style={styles.btnGhost} onPress={lambda { editing = False; }}>
                    <Text style={styles.btnGhostText}>Cancel</Text>
                </Pressable>
            </View>
        </View>;
    }

    def Merchant() -> JsxElement {
        return <View style={styles.content}>
            <View style={styles.header}>
                <Text style={styles.brand}>MERCHANT</Text>
                <Text style={styles.title}>Profile and offers</Text>
            </View>
            <MerchantPicker />
            {(
                <View style={styles.empty}><Text style={styles.subtitle}>Loading restaurant...</Text></View>
            ) if mLoading else (<View />) if portal is None else <View style={{"gap": 16}}>
                <Message text={mMsg} good={mOk} />
                {Editor() if editing else <View />}
                <View style={styles.section}>
                    <View style={styles.rowBetween}>
                        <Text style={styles.h2}>Your offers</Text>
                        <Pressable style={styles.btnGhost} onPress={lambda { newOffer(); }}>
                            <Text style={styles.btnGhostText}>New offer</Text>
                        </Pressable>
                    </View>
                    {(<Text style={styles.small}>No offers yet. Create your first one.</Text>) if not portal.offers else <View />}
                    {[
                        <View key={o.id} style={styles.card}>
                            <View style={styles.rowBetween}>
                                <Text style={[styles.offerTitle, styles.flex1]}>{o.title}</Text>
                                <StatusPill state={o.state} />
                            </View>
                            <Text style={styles.body}>{money(o.price) + "  ·  " + o.time_label}</Text>
                            <Text style={styles.small}>{str(o.remaining) + " of " + str(o.quantity) + " available"}</Text>
                            <View style={styles.row}>
                                <Pressable style={styles.btnGhost} onPress={lambda { editOffer(o); }}>
                                    <Text style={styles.btnGhostText}>Edit</Text>
                                </Pressable>
                                <Pressable style={styles.btnGhost} onPress={lambda { toggleStatus(o); }}>
                                    <Text style={styles.btnGhostText}>{"Resume" if o.state == "paused" else "Pause"}</Text>
                                </Pressable>
                            </View>
                        </View>
                        for o in portal.offers
                    ]}
                </View>
                <View style={styles.section}>
                    <Text style={styles.h2}>Restaurant profile</Text>
                    <Field label="Name" value={pName} onChange={lambda (t: str) { pName = t; }} placeholder="Restaurant name" multiline={False} />
                    <Field label="Cuisine" value={pCuisine} onChange={lambda (t: str) { pCuisine = t; }} placeholder="Noodles" multiline={False} />
                    <Field label="About" value={pBlurb} onChange={lambda (t: str) { pBlurb = t; }} placeholder="Short description" multiline={True} />
                    <Field label="Address" value={pAddress} onChange={lambda (t: str) { pAddress = t; }} placeholder="Street address" multiline={False} />
                    <Field label="Neighborhood" value={pHood} onChange={lambda (t: str) { pHood = t; }} placeholder="Kerrytown" multiline={False} />
                    <Field label="Entrance or construction note" value={pNote} onChange={lambda (t: str) { pNote = t; }} placeholder="Use the side door while sidewalk work continues" multiline={True} />
                    <Field label="Note date" value={pNoteDate} onChange={lambda (t: str) { pNoteDate = t; }} placeholder="2026-09-26" multiline={False} />
                    <Pressable style={styles.btn} disabled={busy} onPress={lambda { saveProfile(); }}>
                        <Text style={styles.btnText}>Save profile</Text>
                    </Pressable>
                </View>
            </View>}
        </View>;
    }

    def Redeem() -> JsxElement {
        return <View style={styles.content}>
            <View style={styles.header}>
                <Text style={styles.brand}>COUNTER</Text>
                <Text style={styles.title}>Redeem a claim</Text>
                <Text style={styles.subtitle}>Enter the six-character code the student shows you.</Text>
            </View>
            <MerchantPicker />
            {(<View />) if portal is None else <View style={{"gap": 16}}>
                <View style={styles.section}>
                    <Text style={styles.restaurant}>{portal.name}</Text>
                    <TextInput
                        style={[styles.input, {"fontSize": 24, "fontWeight": "800", "letterSpacing": 4, "textAlign": "center"}]}
                        value={code}
                        placeholder="ABC123"
                        placeholderTextColor={C["muted"]}
                        autoCapitalize="characters"
                        maxLength={6}
                        onChangeText={lambda (t: str) { code = t.upper(); }}
                        onSubmitEditing={lambda { redeem(); }}
                    />
                    <Pressable style={styles.btn} disabled={busy} onPress={lambda { redeem(); }}>
                        <Text style={styles.btnText}>{"Checking..." if busy else "Redeem code"}</Text>
                    </Pressable>
                    <Message text={rMsg} good={rOk} />
                </View>
                <View style={styles.section}>
                    <Text style={styles.h2}>Recent claims</Text>
                    {(<Text style={styles.small}>No claims yet.</Text>) if not portal.claims else <View />}
                    {[
                        <View key={c.code} style={styles.rowBetween}>
                            <View style={styles.flex1}>
                                <Text style={[styles.body, {"fontWeight": "800", "letterSpacing": 2}]}>{c.code}</Text>
                                <Text style={styles.small}>{c.student_id + " · " + c.offer_title}</Text>
                                <Text style={styles.small}>{"Claimed " + c.claimed_label + ", hold until " + c.expires_label}</Text>
                            </View>
                            <StatusPill state={c.status} />
                        </View>
                        for c in portal.claims
                    ]}
                </View>
            </View>}
        </View>;
    }

    def TabButton(id: str, label: str, sub: str) -> JsxElement {
        on = tab == id;
        return <Pressable style={[styles.tab, styles.tabOn if on else {}]} onPress={lambda { goTab(id); }}>
            <Text style={[styles.tabText, styles.tabTextOn if on else {}]}>{label}</Text>
            <Text style={styles.tabSub}>{sub}</Text>
        </Pressable>;
    }

    body = (Detail() if selected else Discover()) if tab == "discover" else Merchant() if tab == "merchant" else Redeem();

    return <View style={[styles.screen, {"height": viewport.height}]}>
        <View style={styles.frame}>
            <ScrollView style={[styles.scroll, {"height": viewport.height}]}>{body}</ScrollView>
            <View style={styles.tabbar}>
                {TabButton("discover", "Offers", "Student")}
                {TabButton("merchant", "Manage", "Merchant")}
                {TabButton("redeem", "Redeem", "Merchant")}
            </View>
        </View>
    </View>;
}
