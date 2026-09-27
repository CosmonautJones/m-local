"""
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
    resolve_claim,
    redeem_claim,
    cancel_claim,
    offer_defaults,
    OfferView,
    MerchantView,
    ActionResult,
    ClaimView
}
import from services.session { current_session, SessionView }
import from services.onboarding { request_email_code, verify_email_code }
import from services.business_onboarding { get_business_draft, import_business_website, save_business_draft }

import from "@jac/mobui" {
    View,
    Text,
    Pressable,
    TextInput,
    ScrollView,
    useWindowDimensions
}
import from .theme { C, buildStyles, statusColors, money }
import from .services.session { SessionView }
import from .client.session { signIn, signOut, loadSession, acceptEmailToken }
import from './client/onboarding.jsx' { EmailOnboarding, BusinessOnboarding, AudienceWelcome, readAudience, rememberAudience, clearAudience, audienceForSession }
import from './client/qr.jsx' { ClaimQr, ClaimScanner }
import from './client/scan-controller.mjs' { isClaimPayload }


glob styles = buildStyles(C);

glob DIETS: list[str] = ["vegetarian", "vegan", "gluten-free", "halal"];

glob WINDOWS: list[list[str]] = [["any", "Any time"], ["now", "Right now"], ["today", "Today"]];

glob BUDGETS: list[str] = ["", "5", "8", "10"];



def Chip(label: str, on: bool, onPress: any) -> JsxElement {
    return <Pressable accessibilityRole="button" style={[styles.chip, styles.chipOn if on else {}]} onPress={onPress}>
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
            accessibilityLabel={label}
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
    hasSavedClaim = o.my_claim_id != "" and o.my_status in ["claimed", "redeemed"];
    saving = o.regular_price - o.price;
    live = o.state == "active";
    status = (
        "Your QR is ready" if o.my_qr_payload and o.my_status == "claimed"
        else "Saved claim redeemed" if hasSavedClaim and o.my_status == "redeemed"
        else "Open your saved claim" if hasSavedClaim
        else o.time_label + "  ·  " + str(o.remaining) + " left" if live
        else o.time_label if o.state == "scheduled" else o.state.capitalize()
    );
    return <Pressable accessibilityRole="button" style={[styles.card, {} if live or hasSavedClaim else styles.cardMuted]} onPress={onOpen}>
        <View style={styles.rowBetween}>
            <Text style={styles.restaurant}>{o.restaurant.replace(" (Demo)", "")}</Text>
            {(<DemoTag />) if o.is_demo else <View />}
        </View>
        <Text style={styles.offerTitle}>{o.my_title if hasSavedClaim else o.title}</Text>
        <View style={styles.rowBetween}>
            <View style={styles.row}>
                <Text style={styles.price}>{money(o.my_price_cents / 100) if hasSavedClaim else money(o.price)}</Text>
                {(<Text style={styles.strike}>{money(o.regular_price)}</Text>) if saving > 0 and not hasSavedClaim else <View />}
            </View>
            {(
                <View style={styles.badge}>
                    <Text style={styles.badgeText}>{"Save " + money(saving)}</Text>
                </View>
            ) if saving > 0 and not hasSavedClaim else <View />}
        </View>
        <Text style={[styles.small, {"color": C["accent"], "fontWeight": "700"} if o.my_qr_payload else {}]}>{status}</Text>
    </Pressable>;
}


def:pub app -> JsxElement {
    has tab: str = "discover",
        session: SessionView | None = None,
        sessionReady: bool = False,
        audience: str = readAudience(),
        email: str = "",
        password: str = "",
        emailInput: Ref[HTMLInputElement] = Ref(),
        authOpen: bool = False,
        authBusy: bool = False,
        authMsg: str = "",
        businessOpen: bool = False,
        sessionEpoch: Ref[int] = Ref(0),
        offerRequest: Ref[int] = Ref(0),
        detailRequest: Ref[int] = Ref(0),
        busyRef: Ref[bool] = Ref(False),
        authRef: Ref[bool] = Ref(False),
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
        detailError: str = "";

    viewport = useWindowDimensions();

    async def loadOffers(price: str, win: str, ds: list[str]) {
        offerRequest.current = (offerRequest.current or 0) + 1;
        requestId = offerRequest.current;
        epoch = sessionEpoch.current;
        found: list[OfferView] = [];
        loading = True;
        loadError = "";
        try {
            found = await list_offers(price, win, ",".join(ds));
            if requestId == offerRequest.current and epoch == sessionEpoch.current { offers = found; }
        } except Exception {
            if requestId == offerRequest.current and epoch == sessionEpoch.current { loadError = "Could not load offers. Check your connection and tap Refresh offers."; }
        } finally {
            if requestId == offerRequest.current and epoch == sessionEpoch.current { loading = False; }
        }
    }

    async can with entry {
        epoch = sessionEpoch.current;
        restored: SessionView | None = None;
        try {
            restored = await loadSession();
            if epoch == sessionEpoch.current {
                session = restored;
                restoredAudience = audienceForSession(restored);
                if restoredAudience { audience = restoredAudience; rememberAudience(restoredAudience); }
            }
        } except Exception {
            if epoch == sessionEpoch.current { authMsg = "Could not check your session. You can still browse; retry sign-in when connected."; }
        }
        if epoch == sessionEpoch.current { sessionReady = True; await loadOffers("", "any", []); }
    }

    async def refresh() { await loadOffers(maxPrice, timeWin, diets); }

    def chooseAudience(kind: str) {
        audience = kind; rememberAudience(kind); authOpen = True; authMsg = "";
    }

    def clearPrivate() {
        sessionEpoch.current = (sessionEpoch.current or 0) + 1;
        offerRequest.current = (offerRequest.current or 0) + 1;
        detailRequest.current = (detailRequest.current or 0) + 1;
        offers = []; detail = None; selected = ""; portal = None;
        claimMsg = ""; mMsg = ""; editing = False; busy = False;
        busyRef.current = False; detailLoading = False; mLoading = False;
        pName = ""; pCuisine = ""; pBlurb = ""; pAddress = "";
        pHood = ""; pNote = ""; pNoteDate = "";
        eTitle = ""; eDesc = ""; eTerms = ""; eMsg = "";
    }

    async def finishSignIn(fresh: SessionView) {
        clearPrivate(); session = fresh; authOpen = False; password = "";
        freshAudience = audienceForSession(fresh);
        if freshAudience { audience = freshAudience; rememberAudience(freshAudience); }
        businessOpen = fresh.role == "business";
        await refresh();
        if fresh.role == "merchant" { await openMerchant(); }
    }

    async def finishEmail(token: str) {
        fresh: SessionView | None = None;
        fresh = await acceptEmailToken(token);
        if fresh { await finishSignIn(fresh); }
    }

    def logout() {
        signOut(); clearAudience(); audience = "";
        clearPrivate(); session = None; password = "";
        tab = "discover"; authOpen = False; businessOpen = False; authMsg = ""; refresh();
    }

    def pickBudget(v: str) { maxPrice = v; loadOffers(v, timeWin, diets); }
    def pickWindow(v: str) { timeWin = v; loadOffers(maxPrice, v, diets); }
    def toggleDiet(d: str) {
        nxt = [x for x in diets if x != d] if d in diets else diets + [d];
        diets = nxt; loadOffers(maxPrice, timeWin, nxt);
    }

    async def openOffer(oid: str) {
        detailRequest.current = (detailRequest.current or 0) + 1;
        requestId = detailRequest.current; epoch = sessionEpoch.current;
        found: OfferView | None = None;
        selected = oid; claimMsg = ""; detailError = ""; detail = None; detailLoading = True;
        try {
            found = await get_offer(oid, maxPrice, timeWin, ",".join(diets));
            if requestId == detailRequest.current and epoch == sessionEpoch.current { detail = found; }
        } except Exception {
            if requestId == detailRequest.current and epoch == sessionEpoch.current { detailError = "Could not load this offer. Check your connection and try again."; }
        } finally {
            if requestId == detailRequest.current and epoch == sessionEpoch.current { detailLoading = False; }
        }
    }

    def openSignIn() {
        authOpen = True;
        if emailInput.current { emailInput.current.focus(); }
    }

    async def changeClaim(cancel: bool) {
        if not session or session.role != "student" { openSignIn(); return; }
        if busyRef.current or not selected { return; }
        busyRef.current = True; busy = True;
        epoch = sessionEpoch.current; requestId = detailRequest.current; oid = selected;
        res: ActionResult | None = None; found: OfferView | None = None;
        try {
            if cancel { res = await cancel_claim(oid); }
            else { res = await claim_offer(oid); }
            if epoch != sessionEpoch.current { return; }
            if requestId == detailRequest.current { claimOk = res.ok; claimMsg = res.message; }
            found = await get_offer(oid, maxPrice, timeWin, ",".join(diets));
            if epoch != sessionEpoch.current { return; }
            if requestId == detailRequest.current { detail = found; }
            await refresh();
        } except Exception {
            if epoch == sessionEpoch.current and requestId == detailRequest.current {
                claimOk = False; claimMsg = "Could not finish updating this claim. Check the connection and retry; an existing hold is kept.";
            }
        } finally {
            if epoch == sessionEpoch.current { busy = False; busyRef.current = False; }
        }
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

    async def openMerchant() {
        epoch = sessionEpoch.current;
        p: MerchantView | None = None;
        mMsg = ""; editing = False; mLoading = True;
        try {
            p = await merchant_portal();
            if epoch != sessionEpoch.current { return; }
            portal = p if p.ok else None;
            if p.ok { fillProfile(p); }
            else { mOk = False; mMsg = p.message; }
        } except Exception {
            if epoch == sessionEpoch.current { mOk = False; mMsg = "Could not load your restaurant. Check the connection and retry."; }
        } finally { if epoch == sessionEpoch.current { mLoading = False; } }
    }

    async def reloadPortal() {
        epoch = sessionEpoch.current;
        p: MerchantView | None = None;
        p = await merchant_portal();
        if epoch == sessionEpoch.current { portal = p if p.ok else None; }
    }

    async def saveProfile() {
        if busyRef.current { return; }
        busyRef.current = True; busy = True; epoch = sessionEpoch.current;
        p: MerchantView | None = None;
        try {
            p = await update_profile(pName, pCuisine, pBlurb, pAddress, pHood, pNote, pNoteDate);
            if epoch != sessionEpoch.current { return; }
            mOk = p.ok; mMsg = p.message;
            if p.ok { portal = p; }
            await refresh();
        } except Exception {
            if epoch == sessionEpoch.current { mOk = False; mMsg = "Profile could not be saved. Your entries are kept; check the connection and retry."; }
        } finally { if epoch == sessionEpoch.current { busy = False; busyRef.current = False; } }
    }

    async def newOffer() {
        if busyRef.current { return; }
        busyRef.current = True; busy = True; epoch = sessionEpoch.current;
        d: list[str] = [];
        try {
            d = await offer_defaults();
            if epoch != sessionEpoch.current { return; }
            eId = ""; eTitle = ""; eDesc = ""; ePrice = ""; eRegular = "";
            eStart = d[0]; eEnd = d[1]; eQty = "10";
            eElig = "Students with a valid university ID";
            eTerms = ""; eDiets = ""; eItem = ""; eMsg = ""; editing = True;
        } except Exception {
            if epoch == sessionEpoch.current { mOk = False; mMsg = "Could not start an offer. Check the connection and retry."; }
        } finally { if epoch == sessionEpoch.current { busy = False; busyRef.current = False; } }
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
        if busyRef.current { return; }
        busyRef.current = True; busy = True; epoch = sessionEpoch.current;
        res: ActionResult | None = None;
        try {
            res = await save_offer(eId, eTitle, eDesc, ePrice, eRegular, eStart, eEnd, eQty, eElig, eTerms, eDiets, eItem);
            if epoch != sessionEpoch.current { return; }
            if res.ok {
                editing = False; mOk = True; mMsg = res.message;
                # The save is confirmed even if fetching the updated list fails.
                try { await reloadPortal(); }
                except Exception {
                    if epoch == sessionEpoch.current {
                        mOk = False;
                        mMsg = res.message + " The restaurant list could not refresh. Use Refresh restaurant to update it.";
                    }
                }
                if epoch == sessionEpoch.current { await refresh(); }
            } else { eMsg = res.message; }
        } except Exception {
            if epoch == sessionEpoch.current { eMsg = "Could not save the offer. Your entries are kept; check the connection and retry."; mOk = False; mMsg = eMsg; }
        } finally { if epoch == sessionEpoch.current { busy = False; busyRef.current = False; } }
    }

    async def toggleStatus(o: OfferView) {
        if busyRef.current { return; }
        busyRef.current = True; busy = True; epoch = sessionEpoch.current;
        res: ActionResult | None = None;
        try {
            res = await set_offer_status(o.id, "active" if o.state == "paused" else "paused");
            if epoch != sessionEpoch.current { return; }
            mOk = res.ok; mMsg = res.message; await reloadPortal(); await refresh();
        } except Exception {
            if epoch == sessionEpoch.current { mOk = False; mMsg = "Could not update the offer. Check the connection and retry."; }
        } finally { if epoch == sessionEpoch.current { busy = False; busyRef.current = False; } }
    }

    async def afterRedeemed() {
        try { await reloadPortal(); await refresh(); }
        except Exception { mOk = False; mMsg = "Redemption was confirmed. Refresh to update recent claims."; }
    }

    def closeDetail() {
        detailRequest.current = (detailRequest.current or 0) + 1;
        selected = ""; detail = None; detailLoading = False;
    }

    def goTab(t: str) {
        tab = t; closeDetail();
        if t != "discover" and session and session.role == "merchant" and not portal { openMerchant(); }
    }

    def SessionPanel() -> JsxElement {
        return <View style={[styles.section, {"marginHorizontal": 20, "marginTop": 16}]}>
            {(
                <View style={{"gap": 12}}><View style={styles.rowBetween}>
                    <View style={styles.flex1}>
                        <Text style={styles.body}>{session.display_name or "Signed in"}</Text>
                        <Text style={styles.small}>{("Email verified" if session.email_verified else session.role.capitalize()) + (" · demo account" if session.is_demo else "")}</Text>
                    </View>
                    <Pressable accessibilityRole="button" style={styles.btnGhost} disabled={authBusy} onPress={lambda { logout(); }}><Text style={styles.btnGhostText}>Sign out</Text></Pressable>
                </View>
                {(<View style={{"gap": 12}}>
                    <Pressable accessibilityRole="button" style={styles.btnGhost} onPress={lambda { businessOpen = not businessOpen; }}><Text style={styles.btnGhostText}>{"Close business profile" if businessOpen else "Create a business profile"}</Text></Pressable>
                    {(<BusinessOnboarding getDraft={get_business_draft} importWebsite={import_business_website} saveDraft={save_business_draft} />) if businessOpen else <View />}
                </View>) if session.email_verified and session.role == "business" else <View />}
                </View>
            ) if session and session.authenticated else (
                <View style={{"gap": 12}}>
                    <Text style={styles.h2}>{"Your business account" if audience == "business" else "Your U-M account"}</Text>
                    <Text style={styles.small}>Browse freely. Verify your email to create an account or sign back in.</Text>
                    {(
                        <EmailOnboarding kind={audience} requestCode={request_email_code} verifyCode={verify_email_code}
                            onVerified={finishEmail} legacySignIn={signIn} onLegacySession={finishSignIn}
                            inputRef={emailInput} onCancel={lambda { authOpen = False; }} />
                    ) if authOpen else <Pressable accessibilityRole="button" style={styles.btnGhost} onPress={lambda { openSignIn(); }}><Text style={styles.btnGhostText}>Open sign in</Text></Pressable>}
                    <Message text={authMsg} good={False} />
                </View>
            )}
        </View>;
    }

    def MerchantGate() -> JsxElement {
        return <View style={styles.section}>
            <Text style={styles.h2}>Restaurant session required</Text>
            <Text style={styles.body}>{"Your account is a student account. Sign out and use the restaurant account to manage or redeem offers." if session and session.authenticated else "Sign in above with your pre-provisioned restaurant account to manage offers and scan claims."}</Text>
        </View>;
    }

    def Discover() -> JsxElement {
        return <View style={styles.content}>
            <View style={styles.header}>
                <Text style={styles.brand}>PROMOPUSHER · ANN ARBOR</Text>
                <Text style={styles.title}>Hungry? Here is what is good nearby.</Text>
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
                <View style={styles.msgBad}><Text style={styles.msgBadText}>{loadError}</Text><Pressable accessibilityRole="button" style={styles.btnGhost} onPress={lambda { refresh(); }}><Text style={styles.btnGhostText}>Refresh offers</Text></Pressable></View>
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
                    <Text style={styles.subtitle}>{"Loading offer..." if detailLoading else detailError or "Offer not found."}</Text>
                    <Pressable accessibilityRole="button" style={styles.btnGhost} onPress={lambda { closeDetail(); }}><Text style={styles.btnGhostText}>Back to offers</Text></Pressable>
                    {(<Pressable accessibilityRole="button" style={styles.btnGhost} onPress={lambda { openOffer(selected); }}><Text style={styles.btnGhostText}>Retry offer</Text></Pressable>) if detailError else <View />}
                </View>
            </View>;
        }
        o = detail;
        claimable = o.state == "active" and o.my_status in ["", "cancelled", "expired"];
        studentSession = session and session.role == "student";
        hasSavedClaim = o.my_claim_id != "" and o.my_status in ["claimed", "redeemed"];
        saving = o.regular_price - o.price;
        return <View style={styles.content}>
            <Pressable accessibilityRole="button" onPress={lambda { closeDetail(); }}>
                <Text style={styles.link}>Back to offers</Text>
            </Pressable>
            <View style={styles.header}>
                <View style={styles.row}>
                    <Text style={styles.restaurant}>{o.restaurant.replace(" (Demo)", "")}</Text>
                    {(<DemoTag />) if o.is_demo else <View />}
                </View>
                <Text style={styles.title}>{o.my_title if hasSavedClaim else o.title}</Text>
                {(<Text style={styles.subtitle}>{o.description}</Text>) if not hasSavedClaim else <View />}
            </View>
            <View style={styles.row}>
                <Text style={styles.priceBig}>{money(o.my_price_cents / 100) if hasSavedClaim else money(o.price)}</Text>
                {(<Text style={styles.strike}>{money(o.regular_price)}</Text>) if saving > 0 and not hasSavedClaim else <View />}
                {(
                    <View style={styles.badge}><Text style={styles.badgeText}>{"Save " + money(saving)}</Text></View>
                ) if saving > 0 and not hasSavedClaim else <View />}
            </View>
            <View style={styles.row}>
                <StatusPill state={o.my_status if hasSavedClaim else o.state} />
                <Text style={styles.small}>
                    {("Hold expires " + o.my_expires if o.my_status == "claimed" else "Saved claim redeemed") if hasSavedClaim else o.time_label + ("  ·  " + str(o.remaining) + " left" if o.state == "active" else "")}
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
            ) if o.reasons and not hasSavedClaim else <View />}
            {(
                <View style={styles.section}>
                    <Text style={styles.h2}>{"Your saved claim" if o.my_status == "claimed" else "Saved claim · " + o.my_status}</Text>
                    <Text style={styles.offerTitle}>{o.my_title}</Text>
                    <Text style={styles.price}>{money(o.my_price_cents / 100)}</Text>
                    <Text style={styles.body}>{o.my_terms or "No additional terms."}</Text>
                    <Text style={styles.body}>{"For: " + o.my_eligibility}</Text>
                    <Text style={styles.small}>{"Hold expires " + o.my_expires + ". Unused holds release automatically."}</Text>
                    {(<View style={{"gap": 12}}>
                        <Text style={styles.label}>Show this QR at the counter</Text>
                        {(<ClaimQr payload={o.my_qr_payload} expiresTs={o.my_expires_ts} />) if isClaimPayload(o.my_qr_payload) else <Text style={styles.body}>Claim QR unavailable. Refresh this offer.</Text>}
                        <Pressable accessibilityRole="button" style={styles.btnGhost} disabled={busy} onPress={lambda { changeClaim(True); }}><Text style={styles.btnGhostText}>{"Updating..." if busy else "Cancel this hold"}</Text></Pressable>
                    </View>) if o.my_status == "claimed" and o.my_qr_payload else <StatusPill state={o.my_status} />}
                </View>
            ) if o.my_claim_id else <View />}
            <Message text={claimMsg} good={claimOk} />
            <Pressable accessibilityRole="button" style={styles.btnGhost} disabled={busy} onPress={lambda { openOffer(o.id); }}><Text style={styles.btnGhostText}>Refresh offer and claim</Text></Pressable>
            <Pressable accessibilityRole="button"
                style={[styles.btn, {} if claimable and audience == "student" else styles.btnDisabled]}
                disabled={not claimable or busy or audience == "business"}
                onPress={lambda { changeClaim(False); }}
            >
                <Text style={styles.btnText}>
                    {"For U-M customers" if audience == "business" else "Updating..." if busy else "Sign in to claim" if not studentSession and claimable else "Claim this offer" if claimable else "Already claimed" if o.my_status else "Not claimable right now"}
                </Text>
            </Pressable>
            <Text style={styles.small}>Prices exclude tax unless the saved terms say otherwise. The restaurant checks the stated ID requirement.</Text>
            {(
                <View style={styles.note}>
                    <Text style={[styles.noteText, {"fontWeight": "800"}]}>Unverified restaurant note</Text>
                    <Text style={styles.noteText}>{o.entrance_note}</Text>
                    <Text style={styles.noteText}>{("Date provided: " + o.note_date + ". " if o.note_date else "") + "Not independently checked. Confirm current access with the restaurant."}</Text>
                </View>
            ) if o.entrance_note else <View />}
            <View style={styles.section}>
                <Text style={styles.body}>{o.address + (" · " + o.neighborhood if o.neighborhood else "")}</Text>
                {(<View style={{"gap": 8}}>
                    <View style={styles.divider} />
                    <Text style={styles.small}>{"For: " + o.eligibility}</Text>
                    <Text style={styles.small}>{o.terms or "No additional terms."}</Text>
                </View>) if not hasSavedClaim else <View />}
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
                <Pressable accessibilityRole="button" style={[styles.btn, styles.flex1]} disabled={busy} onPress={lambda { submitOffer(); }}>
                    <Text style={styles.btnText}>{"Saving..." if busy else "Save offer"}</Text>
                </Pressable>
                <Pressable accessibilityRole="button" style={styles.btnGhost} onPress={lambda { editing = False; }}>
                    <Text style={styles.btnGhostText}>Cancel</Text>
                </Pressable>
            </View>
        </View>;
    }

    def Merchant() -> JsxElement {
        if not session or session.role != "merchant" { return <View style={styles.content}><MerchantGate /></View>; }
        return <View style={styles.content}>
            <View style={styles.header}>
                <Text style={styles.brand}>MERCHANT</Text>
                <Text style={styles.title}>Profile and offers</Text>
            </View>
            <Pressable accessibilityRole="button" style={styles.btnGhost} disabled={mLoading} onPress={lambda { openMerchant(); }}><Text style={styles.btnGhostText}>Refresh restaurant</Text></Pressable>
            <Message text={mMsg} good={mOk} />
            {(
                <View style={styles.empty}><Text style={styles.subtitle}>Loading restaurant...</Text></View>
            ) if mLoading else (<View />) if portal is None else <View style={{"gap": 16}}>
                <Message text={mMsg} good={mOk} />
                {Editor() if editing else <View />}
                <View style={styles.section}>
                    <View style={styles.rowBetween}>
                        <Text style={styles.h2}>Your offers</Text>
                        <Pressable accessibilityRole="button" style={styles.btnGhost} onPress={lambda { newOffer(); }}>
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
                                <Pressable accessibilityRole="button" style={styles.btnGhost} onPress={lambda { editOffer(o); }}>
                                    <Text style={styles.btnGhostText}>Edit</Text>
                                </Pressable>
                                <Pressable accessibilityRole="button" style={styles.btnGhost} onPress={lambda { toggleStatus(o); }}>
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
                    <Pressable accessibilityRole="button" style={styles.btn} disabled={busy} onPress={lambda { saveProfile(); }}>
                        <Text style={styles.btnText}>{"Saving..." if busy else "Save profile"}</Text>
                    </Pressable>
                </View>
            </View>}
        </View>;
    }

    def Redeem() -> JsxElement {
        if not session or session.role != "merchant" { return <View style={styles.content}><MerchantGate /></View>; }
        return <View style={styles.content}>
            <View style={styles.header}>
                <Text style={styles.brand}>COUNTER</Text>
                <Text style={styles.title}>Scan a claim</Text>
                <Text style={styles.subtitle}>Review the saved offer before redeeming.</Text>
            </View>
            <Message text={mMsg} good={mOk} />
            <Pressable accessibilityRole="button" style={styles.btnGhost} disabled={mLoading} onPress={lambda { openMerchant(); }}><Text style={styles.btnGhostText}>Refresh restaurant</Text></Pressable>
            {(<Text style={styles.small}>Loading your restaurant...</Text>) if mLoading else <View />}
            {(<View />) if portal is None else <View style={{"gap": 16}}>
                <View style={styles.section}>
                    <Text style={styles.restaurant}>{portal.name}</Text>
                    <ClaimScanner key={session.actor_id} resolveClaim={resolve_claim} redeemClaim={redeem_claim} onRedeemed={afterRedeemed} />
                </View>
                <View style={styles.section}>
                    <Text style={styles.h2}>Recent claims</Text>
                    {(<Text style={styles.small}>No claims yet.</Text>) if not portal.claims else <View />}
                    {[
                        <View key={c.claim_id} style={styles.rowBetween}>
                            <View style={styles.flex1}>
                                <Text style={styles.body}>{c.title_snapshot}</Text>
                                <Text style={styles.small}>{money(c.price_cents / 100)}</Text>
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
        return <Pressable accessibilityRole="button" style={[styles.tab, styles.tabOn if on else {}]} onPress={lambda { goTab(id); }}>
            <Text style={[styles.tabText, styles.tabTextOn if on else {}]}>{label}</Text>
            <Text style={styles.tabSub}>{sub}</Text>
        </Pressable>;
    }

    if not sessionReady {
        return <View style={[styles.screen, {"height": viewport.height}]}><View style={styles.empty}><Text style={styles.subtitle}>Opening M-Local...</Text></View></View>;
    }
    if not audience {
        return <View style={[styles.screen, {"height": viewport.height}]}><AudienceWelcome onChoose={chooseAudience} /></View>;
    }

    body = (Detail() if selected else Discover()) if tab == "discover" else Merchant() if tab == "merchant" else Redeem();

    return <View style={[styles.screen, {"height": viewport.height}]}>
        <View style={styles.frame}>
            <ScrollView style={[styles.scroll, {"height": viewport.height}]}>{SessionPanel()}{body}</ScrollView>
            <View style={styles.tabbar}>
                {TabButton("discover", "Offers", "Nearby")}
                {TabButton("merchant", "Manage", "Merchant") if session and session.role == "merchant" else <View />}
                {TabButton("redeem", "Redeem", "Merchant") if session and session.role == "merchant" else <View />}
            </View>
        </View>
    </View>;
}
