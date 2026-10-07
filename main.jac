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
import from services.foryou {
    home_feed,
    taste_choices,
    save_taste,
    toggle_favorite,
    HomeView,
    FeedItem,
    FavoritePlace,
    TasteView,
    Choice
}
import from services.onboarding { request_email_code, verify_email_code }
import from services.business_onboarding { get_business_draft, import_business_website, save_business_draft }
import from services.account_profile { get_account_profile, save_account_profile }
import from services.analytics { merchant_insights, local_activity }
import from services.business_profile { get_business_profile }
import from services.nearby { nearby_after }
import from services.places { list_places, nearby_places }

import from "@jac/mobui" {
    View,
    Text,
    Pressable,
    TextInput,
    ScrollView,
    useWindowDimensions
}
import from .theme { C, buildStyles, statusColors, money }
import from .client.session { signOut, loadSession, acceptEmailToken }
import from .client.onboarding { EmailOnboarding, BusinessOnboarding, AudienceWelcome, audienceForSession }
import from .client.account_profile { AccountProfile }
import from .client.offer_editor { OfferEditor }
import from "./client/qr.jsx" { ClaimQr, ClaimScanner }
import from .client.insights { BusinessInsights }
import from "./client/what-now.jsx" { WhatNow }
# Include the JSX helper explicitly for Jac 0.37.23.
import from "./client/insights-support.mjs" { normalizeInsights }
import from "./client/scan-controller.mjs" { isClaimPayload }
import from "./client/feed-support.jsx" { useFeedRefresh }
import from "./client/feed-validation.mjs" { validateHomeFeed }
import from "./client/public-offer-intent.mjs" { readPublicOfferIntent, rememberPublicOfferIntent, clearPublicOfferIntent }
import from .client.offer_filters { OfferFilters }
import from .client.ui { BrandLogo, UiFoundation, ThemeControl, NavIcon, StockBar }
import from "./client/theme.mjs" { createThemeStore }
import from .client.business_profile { BusinessProfile }
import from "./client/offer-image.jsx" { OfferImage }
import from "./client/photo-picker.jsx" { PhotoPicker }
import from services.photos { upload_business_photo, import_business_photo }


glob styles = buildStyles(C);

def Chip(label: str, on: bool, onPress: any) -> JsxElement {
    return <Pressable accessibilityRole="button" accessibilityState={{"selected": on}} style={[styles.chip, styles.chipOn if on else {}]} onPress={onPress}>
        <Text style={[styles.chipText, styles.chipTextOn if on else {}]}>{label}</Text>
    </Pressable>;
}


def StatusPill(state: str) -> JsxElement {
    cols = statusColors(state);
    return <View style={[styles.status, {"backgroundColor": cols[0]}]}>
        <Text style={[styles.statusText, {"color": cols[1]}]}>{state.upper()}</Text>
    </View>;
}


def Message(text: str, good: bool) -> JsxElement {
    if not text {
        return <View style={styles.hidden} />;
    }
    return <View accessibilityRole="alert" accessibilityLiveRegion="polite" style={styles.msgGood if good else styles.msgBad}>
        <Text style={styles.msgGoodText if good else styles.msgBadText}>{text}</Text>
    </View>;
}


def Field(
    label: str, value: str, onChange: any, placeholder: str, multiline: bool, disabled: bool = False
) -> JsxElement {
    return <View style={styles.field}>
        <Text style={styles.label}>{label}</Text>
        <TextInput
            accessibilityLabel={label}
            style={[styles.input, styles.inputMulti if multiline else {}]}
            value={value}
            placeholder={placeholder}
            placeholderTextColor={C["muted"]}
            multiline={multiline}
            editable={not disabled}
            onChangeText={onChange}
        />
    </View>;
}


def AccessContext(o: OfferView) -> JsxElement {
    if o.access_context is not None and o.access_context.state == "current" {
        return <View style={styles.note}>
            <Text style={[styles.noteText, {"fontWeight": "800"}]}>Current access</Text>
            <View>
                {[
                    <Text key={n.id} style={styles.noteText}>{n.entrance_instruction if n.entrance_instruction else n.summary}</Text>
                    for n in o.access_context.notices if n.state == "current"
                ]}
            </View>
        </View>;
    }
    if o.access_context is not None and o.access_context.state == "needs_recheck" {
        return <View style={styles.note}>
            <Text style={[styles.noteText, {"fontWeight": "800"}]}>Access needs a recheck</Text>
            <Text style={styles.noteText}>The last access note for this place is stale. Confirm the entrance with the restaurant.</Text>
        </View>;
    }
    return <View>
        <Text style={styles.small}>No reviewed access information for this place.</Text>
    </View>;
}


def DealCard(item: FeedItem, onOpen: any, onBusiness: any, onHeart: any, canHeart: bool) -> JsxElement {
    o = item.offer;
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
    return <View style={[styles.card, {} if live or hasSavedClaim else styles.cardMuted]}>
        {(<Text style={[styles.small, {"fontWeight": "800", "color": C["warn"]}]}>Sample</Text>) if o.is_demo else <View style={styles.hidden} />}
        {(<Pressable accessibilityRole="button" accessibilityLabel={"View " + o.title} onPress={onOpen}><OfferImage url={o.offer_image_url} width={"100%"} height={184} alt={o.title} /></Pressable>) if o.offer_image_url else <View style={styles.hidden} />}
        <View style={styles.rowBetween}>
            <Pressable accessibilityRole="button" accessibilityLabel={"View " + o.restaurant + " business profile"} style={styles.flex1} onPress={onBusiness}>
                <Text style={styles.restaurant}>{o.restaurant}</Text>
            </Pressable>
            {(
                <Pressable accessibilityRole="button" accessibilityLabel={("Remove " if item.is_favorite else "Add ") + o.restaurant + (" from favorites" if item.is_favorite else " to favorites")}
                    style={{"paddingHorizontal": 12, "paddingVertical": 6, "marginRight": -8}} onPress={onHeart}>
                    <Text style={{"fontSize": 26, "lineHeight": 30, "color": C["accent"] if item.is_favorite else C["muted"]}}>{"♥" if item.is_favorite else "♡"}</Text>
                </Pressable>
            ) if canHeart else <View style={styles.hidden} />}
        </View>
        <Pressable accessibilityRole="button" style={{"gap": 10}} onPress={onOpen}>
            <Text style={styles.offerTitle}>{o.my_title if hasSavedClaim else o.title}</Text>
            <View style={styles.rowBetween}>
                <View style={styles.row}>
                    <Text style={styles.price}>{money(o.my_price_cents / 100) if hasSavedClaim else money(o.price)}</Text>
                    {(<Text style={styles.strike}>{money(o.regular_price)}</Text>) if saving > 0 and not hasSavedClaim else <View style={styles.hidden} />}
                </View>
                {(
                    <View style={styles.badge}>
                        <Text style={styles.badgeText}>{"Save " + money(saving)}</Text>
                    </View>
                ) if saving > 0 and not hasSavedClaim else <View style={styles.hidden} />}
            </View>
            {(
                <View style={styles.wrap}>
                    {[
                        <View key={"l" + l} style={[styles.tag, {"backgroundColor": C["goodSoft"]}]}>
                            <Text style={[styles.tagText, {"color": C["good"]}]}>{l}</Text>
                        </View>
                        for l in item.place_labels
                    ]}
                </View>
            ) if item.place_labels else <View style={styles.hidden} />}
            {(
                <View style={styles.wrap}>
                    {[
                        <View key={"r" + r} style={[styles.tag, {"backgroundColor": C["badSoft"] if r.startswith("Not marked") else C["accentSoft"]}]}>
                            <Text style={[styles.tagText, {"color": C["bad"] if r.startswith("Not marked") else C["accent"]}]}>{r}</Text>
                        </View>
                        for r in item.reasons
                    ]}
                </View>
            ) if item.reasons else <View style={styles.hidden} />}
            <Text style={[styles.small, {"color": C["accent"], "fontWeight": "700"} if o.my_qr_payload else {}]}>{status}</Text>
            {(<StockBar remaining={o.remaining} total={o.quantity} />) if live and not hasSavedClaim else <View style={styles.hidden} />}
        </Pressable>
    </View>;
}


def FavoriteChip(f: FavoritePlace, onOpen: any, onRemove: any) -> JsxElement {
    return <View style={[styles.card, {"width": 190, "gap": 4, "paddingVertical": 12}]}>
      <Pressable accessibilityRole="button" style={{"gap": 4}} onPress={onOpen}>
        <View style={styles.row}>
            <Text style={{"fontSize": 16, "color": C["accent"]}}>{"♥"}</Text>
            <Text style={[styles.restaurant, styles.flex1]} numberOfLines={1}>{f.name}</Text>
        </View>
        <Text style={styles.small} numberOfLines={1}>{f.cuisine}</Text>
        {(<Text style={[styles.tagText, {"color": C["good"]}]} numberOfLines={1}>{" · ".join(f.labels[:2])}</Text>) if f.labels else <View style={styles.hidden} />}
        <Text style={[styles.small, {"color": C["ink"], "fontWeight": "700"}]} numberOfLines={1}>
            {(money(f.best_price_cents / 100) + " · " + f.best_offer_title) if f.best_offer_id else "No deal right now"}
        </Text>
      </Pressable>
      <Pressable accessibilityRole="button" accessibilityLabel={"Remove " + f.name + " from favorites"} style={styles.btnGhost} onPress={onRemove}><Text style={styles.btnGhostText}>Remove favorite</Text></Pressable>
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
            <Text style={styles.restaurant}>{o.restaurant}</Text>
        </View>
        <Text style={styles.offerTitle}>{o.my_title if hasSavedClaim else o.title}</Text>
        <View style={styles.rowBetween}>
            <View style={styles.row}>
                <Text style={styles.price}>{money(o.my_price_cents / 100) if hasSavedClaim else money(o.price)}</Text>
                {(<Text style={styles.strike}>{money(o.regular_price)}</Text>) if saving > 0 and not hasSavedClaim else <View style={styles.hidden} />}
            </View>
            {(
                <View style={styles.badge}>
                    <Text style={styles.badgeText}>{"Save " + money(saving)}</Text>
                </View>
            ) if saving > 0 and not hasSavedClaim else <View style={styles.hidden} />}
        </View>
        <Text style={[styles.small, {"color": C["accent"], "fontWeight": "700"} if o.my_qr_payload else {}]}>{status}</Text>
            {(<StockBar remaining={o.remaining} total={o.quantity} />) if live and not hasSavedClaim else <View style={styles.hidden} />}
    </Pressable>;
}


def:pub app -> JsxElement {
    has tab: str = "discover",
        session: SessionView | None = None,
        sessionReady: bool = False,
        audience: str = "",
        email: str = "",
        emailInput: Ref[HTMLInputElement] = Ref(),
        authOpen: bool = False,
        authMode: str = "signin",
        authBusy: bool = False,
        authMsg: str = "",
        businessOpen: bool = False,
        profileEditing: bool = False,
        localActivity: bool = False,
        profileOpen: bool = False,
        profileSlug: str = "",
        profileOfferId: str = "",
        accountOpen: bool = False,
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
        ePhoto: str = "",
        pPhoto: str = "",
        eMsg: str = "",
        detailError: str = "",
        home: HomeView | None = None,
        tastes: TasteView | None = None,
        tastesOpen: bool = False,
        tastePrompted: bool = False,
        tasteBusy: bool = False,
        tasteMsg: str = "",
        pickCats: list[str] = [],
        pickDiets: list[str] = [],
        pickRange: str = "";

    viewport = useWindowDimensions();
    useFeedRefresh({
        "enabled": sessionReady and audience == "student" and not authOpen and tab == "discover" and selected == "" and not tastesOpen and not profileOpen,
        "onRefresh": lambda { return refresh(); },
        "busy": loading
    });
    useFeedRefresh({
        "enabled": sessionReady and session is not None and session.authenticated and session.role == "student" and selected != "" and detail is not None and detail.my_status == "claimed" and not authOpen and not profileOpen and tab == "discover",
        "onRefresh": lambda { return refreshHeldClaim(); },
        "busy": busy or detailLoading,
        "interval": 15000
    });

    def publicOffer(o: OfferView) -> OfferView {
        o.my_claim_id = ""; o.my_status = ""; o.my_qr_payload = "";
        o.my_title = ""; o.my_price_cents = 0; o.my_terms = ""; o.my_eligibility = "";
        o.my_expires = ""; o.my_expires_ts = 0.0;
        return o;
    }

    async def openTastes() {
        found: TasteView | None = None;
        tasteMsg = "";
        try {
            found = await taste_choices();
            if found {
                tastes = found;
                pickCats = found.categories;
                pickDiets = found.diets;
                pickRange = found.price_range;
                tastesOpen = True;
            }
        } except Exception {
            tasteMsg = "Could not load the choices. Check your connection and try again.";
        }
    }

    def togglePickCat(k: str) { pickCats = [x for x in pickCats if x != k] if k in pickCats else pickCats + [k]; }
    def togglePickDiet(k: str) { pickDiets = [x for x in pickDiets if x != k] if k in pickDiets else pickDiets + [k]; }
    def choosePickRange(k: str) { pickRange = "" if pickRange == k else k; }

    async def submitTastes(blank: bool) {
        if tasteBusy { return; }
        tasteBusy = True; tasteMsg = "";
        saved: TasteView | None = None;
        try {
            if blank { saved = await save_taste("", "", ""); }
            else { saved = await save_taste(",".join(pickCats), ",".join(pickDiets), pickRange); }
            if saved and saved.ok {
                tastes = saved; tastesOpen = False;
                await loadOffers(maxPrice, timeWin, diets);
            } else {
                tasteMsg = "Could not save. Sign in again and retry.";
            }
        } except Exception {
            tasteMsg = "Could not save. Check your connection and try again.";
        } finally {
            tasteBusy = False;
        }
    }

    async def toggleHeart(item: FeedItem) {
        if not session or not session.authenticated {
            openSignIn(); authMsg = "Sign in to save your favorite places.";
            return;
        }
        if session.role != "student" { return; }
        try {
            await toggle_favorite(item.place, "");
            await loadOffers(maxPrice, timeWin, diets);
        } except Exception {
            loadError = "Could not update favorites. Check your connection and try again.";
        }
    }

    async def loadOffers(price: str, win: str, ds: list[str]) {
        offerRequest.current = (offerRequest.current or 0) + 1;
        requestId = offerRequest.current;
        epoch = sessionEpoch.current;
        found: HomeView | None = None;
        loading = True;
        loadError = "";
        try {
            found = validateHomeFeed(await home_feed(price, win, ",".join(ds)));
            if found and requestId == offerRequest.current and epoch == sessionEpoch.current {
                if not found.show_samples {
                    found.items = [item for item in found.items if not item.offer.is_demo];
                    found.favorites = [place for place in found.favorites if not place.is_demo];
                }
                if not session or not session.authenticated {
                    for item in found.items { item.offer = publicOffer(item.offer); }
                }
                home = found;
                offers = [i.offer for i in found.items];
                if found.signed_in and not found.completed and not tastePrompted and session and session.role == "student" {
                    tastePrompted = True;
                    openTastes();
                }
            }
        } except Exception {
            if requestId == offerRequest.current and epoch == sessionEpoch.current { loadError = "Could not load offers. Check your connection and tap Refresh offers."; }
        } finally {
            if requestId == offerRequest.current and epoch == sessionEpoch.current { loading = False; }
        }
    }

    async can with entry {
        epoch = sessionEpoch.current;
        selectionRevision = detailRequest.current;
        pending = readPublicOfferIntent();
        restored: SessionView | None = None;
        try {
            restored = await loadSession();
            if epoch == sessionEpoch.current {
                session = restored;
                restoredAudience = audienceForSession(restored);
                if restoredAudience { audience = restoredAudience; }
            }
        } except Exception {
            if epoch == sessionEpoch.current { authMsg = "Could not check your session. Retry sign-in when connected."; }
        }
        if epoch == sessionEpoch.current {
            sessionReady = True;
            if restored is not None and restored.authenticated and restored.role == "student" { await loadOffers("", "any", []); }
            if epoch == sessionEpoch.current and pending and (restored is None or not restored.authenticated or restored.role == "student") {
                audience = "student";
                if restored is None or not restored.authenticated { await loadOffers("", "any", []); }
                if epoch == sessionEpoch.current and selectionRevision == detailRequest.current { await openOffer(pending); }
            }
        }
        if epoch == sessionEpoch.current and restored is not None and restored.authenticated and restored.role == "merchant" {
            tab = "merchant"; await openMerchant();
        }
        if epoch == sessionEpoch.current and restored is not None and restored.authenticated and restored.role == "business" {
            businessOpen = True;
        }
    }

    async def refresh() { await loadOffers(maxPrice, timeWin, diets); }

    def chooseAudience(kind: str) {
        audience = kind; authOpen = kind == "business"; authMode = "signup"; authMsg = "";
        if kind == "student" { loadOffers(maxPrice, timeWin, diets); }
    }

    def switchAudience(kind: str) {
        audience = kind; authMsg = "";
    }

    async def refreshAccount(_displayName: str) {
        epoch = sessionEpoch.current;
        fresh: SessionView | None = None;
        try {
            fresh = await loadSession();
            if epoch == sessionEpoch.current { session = fresh; authMsg = ""; }
        } except Exception {
            if epoch == sessionEpoch.current { authMsg = "Your account was saved. Refresh the page to update the name shown here."; }
        }
    }

    async def openActivatedBusiness() -> bool {
        epoch = sessionEpoch.current;
        fresh: SessionView | None = None;
        try { fresh = await loadSession(); }
        except Exception { return False; }
        if epoch != sessionEpoch.current { return False; }
        if fresh is None { return False; }
        if not fresh.authenticated or fresh.role != "merchant" or not fresh.restaurant_id { return False; }
        session = fresh; businessOpen = False; tab = "merchant";
        await openMerchant();
        return True;
    }

    def clearPrivate() {
        sessionEpoch.current = (sessionEpoch.current or 0) + 1;
        offerRequest.current = (offerRequest.current or 0) + 1;
        detailRequest.current = (detailRequest.current or 0) + 1;
        offers = []; detail = None; selected = ""; portal = None;
        profileOpen = False; profileSlug = ""; profileOfferId = "";
        claimMsg = ""; mMsg = ""; editing = False; profileEditing = False; busy = False; accountOpen = False;
        busyRef.current = False; detailLoading = False; mLoading = False;
        pName = ""; pCuisine = ""; pBlurb = ""; pAddress = "";
        pHood = ""; pNote = ""; pNoteDate = "";
        eTitle = ""; eDesc = ""; eTerms = ""; eMsg = "";
    }

    async def finishSignIn(fresh: SessionView) {
        pending = readPublicOfferIntent();
        clearPrivate(); session = fresh; authOpen = False;
        epoch = sessionEpoch.current; selectionRevision = detailRequest.current;
        freshAudience = audienceForSession(fresh);
        if freshAudience { audience = freshAudience; }
        businessOpen = fresh.role == "business";
        if fresh.role == "student" {
            tab = "discover"; await refresh();
            if pending and epoch == sessionEpoch.current and selectionRevision == detailRequest.current { await openOffer(pending); }
        } else { clearPublicOfferIntent(); }
        if fresh.role == "merchant" { tab = "merchant"; await openMerchant(); }
    }

    async def finishEmail(token: str) {
        fresh: SessionView | None = None;
        fresh = await acceptEmailToken(token);
        if fresh { await finishSignIn(fresh); }
    }

    def logout() {
        if session and session.actor_id {
            try { localStorage.removeItem("mlocal_offer_draft_" + session.actor_id); } except Exception {}
        }
        signOut(); clearPrivate(); clearPublicOfferIntent(); session = None; audience = "";
        tab = "discover"; authOpen = False; businessOpen = False; authMsg = ""; home = None;
    }

    def applyFilters(price: str, win: str, selectedDiets: list[str]) {
        maxPrice = price; timeWin = win; diets = selectedDiets;
        loadOffers(price, win, selectedDiets);
    }

    async def openOffer(oid: str) {
        rememberPublicOfferIntent(oid);
        detailRequest.current = (detailRequest.current or 0) + 1;
        requestId = detailRequest.current; epoch = sessionEpoch.current;
        found: OfferView | None = None;
        selected = oid; claimMsg = ""; detailError = ""; detail = None; detailLoading = True;
        try {
            found = await get_offer(oid, maxPrice.split("-")[-1] if maxPrice else "", timeWin, ",".join(diets));
            if requestId == detailRequest.current and epoch == sessionEpoch.current {
                detail = publicOffer(found) if found is not None and (not session or not session.authenticated) else found;
                if found is None { detailError = "This offer is no longer available."; clearPublicOfferIntent(); }
            }
        } except Exception {
            if requestId == detailRequest.current and epoch == sessionEpoch.current { detailError = "Could not load this offer. Check your connection and try again."; }
        } finally {
            if requestId == detailRequest.current and epoch == sessionEpoch.current { detailLoading = False; }
        }
    }

    def openSignIn() {
        authOpen = True; authMode = "signin";
        if emailInput.current { emailInput.current.focus(); }
    }

    async def changeClaim(cancel: bool) {
        if not session or not session.authenticated or session.role != "student" {
            if selected { rememberPublicOfferIntent(selected); }
            openSignIn(); authMsg = "Sign in with your U-M email to claim this deal.";
            return;
        }
        if busyRef.current or not selected { return; }
        busyRef.current = True; busy = True;
        epoch = sessionEpoch.current; requestId = detailRequest.current; oid = selected;
        res: ActionResult | None = None; found: OfferView | None = None;
        try {
            if cancel { res = await cancel_claim(oid); }
            else { res = await claim_offer(oid); }
            if epoch != sessionEpoch.current { return; }
            if requestId == detailRequest.current { claimOk = res.ok; claimMsg = res.message; }
            found = await get_offer(oid, maxPrice.split("-")[-1] if maxPrice else "", timeWin, ",".join(diets));
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

    async def refreshHeldClaim() {
        if busyRef.current or not selected or not detail or detail.my_status != "claimed" { return; }
        epoch = sessionEpoch.current; oid = selected;
        detailRequest.current = (detailRequest.current or 0) + 1;
        requestId = detailRequest.current;
        found: OfferView | None = None;
        try {
            found = await get_offer(oid, maxPrice.split("-")[-1] if maxPrice else "", timeWin, ",".join(diets));
            if epoch != sessionEpoch.current or requestId != detailRequest.current or selected != oid { return; }
            if found is None {
                detail = None; detailError = "This offer is no longer available.";
            } else {
                detail = found;
                if found.my_status == "redeemed" { claimOk = True; claimMsg = "Your saved claim was redeemed."; }
                elif found.my_status == "expired" { claimOk = False; claimMsg = "Your hold has expired. Check current availability before claiming again."; }
            }
        } except Exception {
            if epoch == sessionEpoch.current and requestId == detailRequest.current {
                claimOk = False; claimMsg = "Could not refresh your claim. The saved terms are kept; check your connection and tap Refresh offer and claim.";
            }
        }
    }

    def fillProfile(p: MerchantView) {
        pPhoto = p.image_url;
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
        if epoch == sessionEpoch.current {
            if not p.ok { raise Exception(p.message); }
            portal = p;
        }
    }

    async def saveProfile() {
        if busyRef.current { return; }
        busyRef.current = True; busy = True; epoch = sessionEpoch.current;
        p: MerchantView | None = None;
        try {
            p = await update_profile(pName, pCuisine, pBlurb, pAddress, pHood, pNote, pNoteDate, pPhoto);
            if epoch != sessionEpoch.current { return; }
            mOk = p.ok; mMsg = p.message;
            if p.ok { portal = p; fillProfile(p); profileEditing = False; await refresh(); }
        } except Exception {
            if epoch == sessionEpoch.current { mOk = False; mMsg = "Profile could not be saved. Your entries are kept; check the connection and retry."; }
        } finally { if epoch == sessionEpoch.current { busy = False; busyRef.current = False; } }
    }

    async def newOffer() {
        if busyRef.current { return; }
        busyRef.current = True; busy = True; epoch = sessionEpoch.current; mMsg = "";
        d: list[str] = [];
        try {
            d = await offer_defaults();
            if epoch != sessionEpoch.current { return; }
            eId = ""; eTitle = ""; eDesc = ""; ePrice = ""; eRegular = "";
            eStart = d[0]; eEnd = d[1]; eQty = "10";
            eElig = "Students with a valid university ID";
            eTerms = ""; eDiets = ""; eItem = ""; ePhoto = ""; eMsg = ""; editing = True;
        } except Exception {
            if epoch == sessionEpoch.current { mOk = False; mMsg = "Could not start an offer. Check the connection and retry."; }
        } finally { if epoch == sessionEpoch.current { busy = False; busyRef.current = False; } }
    }

    def editOffer(o: OfferView) {
        mMsg = "";
        eId = o.id;
        eTitle = o.title;
        eDesc = o.description;
        ePrice = str(o.price);
        eRegular = str(o.regular_price) if o.regular_price > 0 else "";
        eStart = o.start_input;
        eEnd = o.end_input;
        eQty = str(o.quantity);
        eElig = o.eligibility;
        eTerms = o.terms;
        eDiets = ", ".join(o.dietary);
        eItem = o.menu_item;
        ePhoto = o.offer_image_url or "";
        eMsg = "";
        editing = True;
    }

    def updateOfferDraft(draft: dict[str, str]) {
        eTitle = draft["title"]; eDesc = draft["description"];
        ePrice = draft["price"]; eRegular = draft["regular_price"];
        eStart = draft["start_local"]; eEnd = draft["end_local"];
        eQty = draft["quantity"]; eElig = draft["eligibility"];
        eTerms = draft["terms"]; eDiets = draft["dietary"]; eItem = draft["menu_item"]; ePhoto = draft["image_url"];
    }

    def setEditorBusy(value: bool) {
        busyRef.current = value; busy = value;
        if value { mMsg = ""; }
    }

    async def afterOfferSaved(message: str) {
        epoch = sessionEpoch.current;
        editing = False; mOk = True; mMsg = message;
        # Publication is confirmed even when refreshing the catalog fails.
        try { await reloadPortal(); }
        except Exception {
            if epoch == sessionEpoch.current {
                mOk = False;
                mMsg = message + " The restaurant list could not refresh. Use Refresh restaurant to update it.";
            }
        }
        if epoch == sessionEpoch.current { await refresh(); }
        if epoch == sessionEpoch.current { busyRef.current = False; busy = False; }
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
        selected = ""; detail = None; detailLoading = False; clearPublicOfferIntent();
    }

    async def dropFavorite(slug: str) {
        try {
            await toggle_favorite(slug, "");
            await loadOffers(maxPrice, timeWin, diets);
        } except Exception {
            loadError = "Could not update favorites. Check your connection and try again.";
        }
    }

    def openBusiness(slug: str, offerId: str = "") {
        if busyRef.current { return; }
        profileSlug = slug; profileOfferId = offerId; profileOpen = True;
    }

    def goTab(t: str) {
        if busyRef.current { return; }
        tab = t; profileOpen = False; closeDetail();
        if t == "account" { accountOpen = True; }
        if t in ["merchant", "redeem"] and session and session.role == "merchant" and not portal { openMerchant(); }
    }

    def closeAuth() {
        authOpen = False; authMsg = "";
        if not (session and session.authenticated) and audience != "student" { audience = ""; }
    }

    def LogoutLink() -> JsxElement {
        if not session or not session.authenticated {
            return <View style={styles.row}><ThemeControl />
                <Pressable accessibilityRole="button" style={styles.btnGhost} onPress={lambda { openSignIn(); }}><Text style={styles.btnGhostText}>Sign in</Text></Pressable>
                <Pressable accessibilityRole="button" style={styles.btnGhost} onPress={lambda { closeDetail(); audience = ""; }}><Text style={styles.btnGhostText}>Choose account type</Text></Pressable>
            </View>;
        }
        return <View style={styles.row}><ThemeControl /><Pressable accessibilityRole="button" accessibilityLabel="Log out" style={styles.btnGhost} disabled={authBusy} onPress={lambda { logout(); }}><Text style={styles.btnGhostText}>Log out</Text></Pressable></View>;
    }

    def AuthScreen() -> JsxElement {
        return <View style={styles.content}>
            <View style={styles.header}>
                <View style={[styles.rowBetween, {"flexWrap": "wrap", "gap": 12}]}><BrandLogo /><ThemeControl /></View>
            </View>
            <Message text={authMsg} good={False} />
            <View style={styles.section}>
                <EmailOnboarding kind={audience} initialMode={authMode} onSwitchAudience={switchAudience} requestCode={request_email_code} verifyCode={verify_email_code}
                    onVerified={finishEmail}
                    inputRef={emailInput} onCancel={lambda { closeAuth(); }} cancelLabel="Back" />
            </View>
        </View>;
    }

    def AccountScreen() -> JsxElement {
        if not session or not session.authenticated { return AuthScreen(); }
        return <View style={styles.content}>
            <View style={styles.header}>
                <View style={styles.rowBetween}>
                    <Text style={styles.brand}>{"YOUR BUSINESS" if session.role in ["business", "merchant"] else "YOUR ACCOUNT"}</Text>
                </View>
                <Text style={styles.title}>{session.display_name or "Signed in"}</Text>
                <Text style={styles.subtitle}>{"Email verified" if session.email_verified else session.role.capitalize()}</Text>
            </View>
            <Message text={authMsg} good={False} />
            {(<View style={styles.section}>
                <BusinessOnboarding key={session.actor_id} getDraft={get_business_draft} importWebsite={import_business_website} saveDraft={save_business_draft} onActivated={openActivatedBusiness} />
            </View>) if session.email_verified and (session.role == "business" or session.business_account) else <View style={styles.hidden} />}
            <View style={styles.section}>
                <Pressable accessibilityRole="button" style={styles.btnGhost} onPress={lambda { accountOpen = not accountOpen; }}><Text style={styles.btnGhostText}>{"Hide account details" if accountOpen else "Account"}</Text></Pressable>
                {(<AccountProfile key={session.actor_id} getProfile={get_account_profile} saveProfile={save_account_profile} onSaved={refreshAccount} />) if accountOpen else <View style={styles.hidden} />}
                {(<Pressable accessibilityRole="button" style={styles.btnGhost} onPress={lambda { tab = "discover"; openTastes(); }}><Text style={styles.btnGhostText}>Edit my tastes</Text></Pressable>) if session.role == "student" else <View style={styles.hidden} />}
                <Pressable accessibilityRole="button" style={styles.btnGhost} disabled={authBusy} onPress={lambda { logout(); }}><Text style={styles.btnGhostText}>Log out of M-Local</Text></Pressable>
            </View>
        </View>;
    }

    def MerchantGate() -> JsxElement {
        return <View style={styles.section}>
            <Text style={styles.h2}>Restaurant session required</Text>
            <Text style={styles.body}>{"Sign in with your business email to manage offers and scan claims."}</Text>
        </View>;
    }

    def Tastes() -> JsxElement {
        return <View style={styles.content}>
            <View style={styles.header}>
                <Text style={styles.brand}>YOUR TASTES</Text>
                <Text style={styles.title}>What do you like?</Text>
                <Text style={styles.subtitle}>Pick anything that fits. We put those deals first, and you will still see everything else.</Text>
            </View>
            <View style={styles.section}>
                <Text style={styles.label}>Food you like</Text>
                <View style={styles.wrap}>
                    {[
                        <Chip key={"c" + c.key} label={c.label} on={c.key in pickCats} onPress={lambda { togglePickCat(c.key); }} />
                        for c in (tastes.all_categories if tastes else [])
                    ]}
                </View>
            </View>
            <View style={styles.section}>
                <Text style={styles.label}>How you eat</Text>
                <View style={styles.wrap}>
                    {[
                        <Chip key={"d" + d.key} label={d.label} on={d.key in pickDiets} onPress={lambda { togglePickDiet(d.key); }} />
                        for d in (tastes.all_diets if tastes else [])
                    ]}
                </View>
            </View>
            <View style={styles.section}>
                <Text style={styles.label}>What you usually spend</Text>
                <View style={styles.wrap}>
                    {[
                        <Chip key={"p" + r.key} label={r.label} on={pickRange == r.key} onPress={lambda { choosePickRange(r.key); }} />
                        for r in (tastes.all_price_ranges if tastes else [])
                    ]}
                </View>
            </View>
            <Message text={tasteMsg} good={False} />
            <Pressable accessibilityRole="button" style={styles.btn} disabled={tasteBusy} onPress={lambda { submitTastes(False); }}>
                <Text style={styles.btnText}>{"Saving..." if tasteBusy else "Save my tastes"}</Text>
            </Pressable>
            <Pressable accessibilityRole="button" style={styles.btnGhost} disabled={tasteBusy} onPress={lambda { submitTastes(True); }}>
                <Text style={styles.btnGhostText}>Skip for now</Text>
            </Pressable>
        </View>;
    }

    def Discover() -> JsxElement {
        if tastesOpen { return Tastes(); }
        signedIn: bool = session is not None and session.authenticated;
        studentSession: bool = session is not None and session.authenticated and session.role == "student";
        claims = [o for o in offers if o.my_status == "claimed" and o.my_claim_id and o.my_qr_payload];
        return <View style={styles.content}>
            <View style={styles.header}>
                <Text style={styles.title}>Local offers</Text>
                {(<Text style={styles.small}>Sample offers · fictional businesses</Text>) if session and session.is_demo else <View style={styles.hidden}/>}
            </View>
            {(<View testID="saved-claims" style={{"gap": 8}}>
                <Text style={styles.h2}>My claims</Text>
                {[<View key={o.id} style={styles.card}>
                    <Text style={styles.small}>{o.restaurant + (" · Until " + o.my_expires if o.my_expires else "")}</Text>
                    <Pressable accessibilityRole="button" style={styles.btn} onPress={lambda { openOffer(o.id); }}>
                        <Text style={styles.btnText}>{"Show QR for " + (o.my_title or o.title)}</Text>
                    </Pressable>
                </View> for o in claims]}
            </View>) if studentSession and len(claims) > 0 else <View style={styles.hidden} />}
            {(
                <View style={{"gap": 8}}>
                    <View style={styles.rowBetween}>
                        <Text style={styles.label}>Your favorites</Text>
                    </View>
                    {(
                        <ScrollView horizontal={True} showsHorizontalScrollIndicator={False} contentContainerStyle={styles.row}>
                            {[<FavoriteChip key={f.slug} f={f} onOpen={lambda { openBusiness(f.slug); }} onRemove={lambda { dropFavorite(f.slug); }} /> for f in home.favorites]}
                        </ScrollView>
                    ) if home and len(home.favorites) > 0 else <Text style={styles.small}>{"Tap the heart on a place to keep it here."}</Text>}
                </View>
            ) if studentSession and home and len(home.favorites) > 0 else (
                <View style={{"gap": 8}}>
                    <Text style={styles.label}>Your favorites</Text>
                    <Pressable accessibilityRole="button" onPress={lambda { openSignIn(); authMsg = "Sign in to save your favorite places."; }}><Text style={styles.small}>{"Sign in, then tap the heart on a place to keep it here."}</Text></Pressable>
                </View>
            ) if not signedIn else <View style={styles.hidden} />}
            <OfferFilters price={maxPrice} time={timeWin} diets={diets} onApply={applyFilters} onRefresh={lambda { refresh(); }} refreshing={loading} />
            {(
                <View style={styles.empty}><Text style={styles.subtitle}>Finding deals...</Text></View>
            ) if loading and not home else (
                <View style={styles.msgBad}><Text style={styles.msgBadText}>{loadError}</Text></View>
            ) if loadError else (
                <View style={styles.empty}>
                    <Text style={styles.h2}>{"Nothing matches yet" if maxPrice != "" or timeWin != "any" or len(diets) > 0 else "Offers are on their way"}</Text>
                    <Text style={styles.small}>{"Try removing a filter." if maxPrice != "" or timeWin != "any" or len(diets) > 0 else "Local businesses will share their offers here. Check back soon."}</Text>
                </View>
            ) if not offers or not home else <View style={{"gap": 12}}>
                {[<DealCard key={i.offer.id} item={i} onOpen={lambda { openOffer(i.offer.id); }} onBusiness={lambda { openBusiness(i.place); }} onHeart={lambda { toggleHeart(i); }} canHeart={not signedIn or studentSession} /> for i in home.items]}
                <Text style={styles.small}>{"Showing " + str(len(home.items)) + (" deal." if len(home.items) == 1 else " deals.") + " Your tastes change the order, never what you can see."}</Text>
            </View>}
        </View>;
    }

    def Detail() -> JsxElement {
        if detailLoading or detail is None {
            return <View style={styles.content}>
                <View style={styles.empty}>
                    <Text style={styles.subtitle}>{"Loading offer..." if detailLoading else detailError or "Offer not found."}</Text>
                    <Pressable accessibilityRole="button" style={styles.btnGhost} onPress={lambda { closeDetail(); }}><Text style={styles.btnGhostText}>Back to offers</Text></Pressable>
                    {(<Pressable accessibilityRole="button" style={styles.btnGhost} onPress={lambda { openOffer(selected); }}><Text style={styles.btnGhostText}>Retry offer</Text></Pressable>) if detailError else <View style={styles.hidden} />}
                </View>
            </View>;
        }
        o = detail;
        claimable = o.state == "active" and o.my_status in ["", "cancelled", "expired"];
        studentSession = session and session.role == "student";
        hasSavedClaim = o.my_claim_id != "" and o.my_status in ["claimed", "redeemed"];
        saving = o.regular_price - o.price;
        return <View style={styles.content}>
            <View style={styles.rowBetween}>
                <Pressable accessibilityRole="button" onPress={lambda { closeDetail(); }}>
                    <Text style={styles.link}>Back to offers</Text>
                </Pressable>
            </View>
            <View style={styles.header}>
                <View style={styles.row}>
                    <Text style={styles.restaurant}>{o.restaurant}</Text>
                </View>
                <Pressable accessibilityRole="button" style={[styles.btnGhost, {"alignSelf": "flex-start"}]} onPress={lambda { openBusiness("", o.id); }}><Text style={styles.btnGhostText}>View business profile</Text></Pressable>
                {(<OfferImage url={o.offer_image_url} width={"100%"} height={220} alt={o.title} />) if o.offer_image_url else <View style={styles.hidden} />}
                <Text style={styles.title}>{o.my_title if hasSavedClaim else o.title}</Text>
                {(<View style={styles.note}><Text style={[styles.noteText, {"fontWeight": "800"}]}>Sample</Text><Text style={styles.noteText}>Sample deal for a local simulation. Confirm real offers directly with the business.</Text></View>) if o.is_demo else <View style={styles.hidden} />}
                {(<Text style={styles.subtitle}>{o.description}</Text>) if not hasSavedClaim else <View style={styles.hidden} />}
            </View>
            <View style={styles.row}>
                <Text style={styles.priceBig}>{money(o.my_price_cents / 100) if hasSavedClaim else money(o.price)}</Text>
                {(<Text style={styles.strike}>{money(o.regular_price)}</Text>) if saving > 0 and not hasSavedClaim else <View style={styles.hidden} />}
                {(
                    <View style={styles.badge}><Text style={styles.badgeText}>{"Save " + money(saving)}</Text></View>
                ) if saving > 0 and not hasSavedClaim else <View style={styles.hidden} />}
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
            ) if o.reasons and not hasSavedClaim else <View style={styles.hidden} />}
            {(
                <View style={styles.claimPass}>
                    {(<Text style={styles.claimBody}>Sample claim for a local simulation.</Text>) if o.is_demo else <View style={styles.hidden} />}
                    <Text style={styles.claimHeading}>{"Your saved claim" if o.my_status == "claimed" else "Saved claim · " + o.my_status}</Text>
                    <Text style={styles.claimHeading}>{o.my_title}</Text>
                    {(<View style={{"gap": 12}}>
                        <Text style={styles.claimLabel}>Show this QR at the counter</Text>
                        {(<ClaimQr payload={o.my_qr_payload} expiresTs={o.my_expires_ts} />) if isClaimPayload(o.my_qr_payload) else <Text style={styles.claimBody}>Claim QR unavailable. Refresh this offer.</Text>}
                        <Pressable accessibilityRole="button" style={styles.btnGhost} disabled={busy} onPress={lambda { changeClaim(True); }}><Text style={styles.btnGhostText}>{"Updating..." if busy else "Cancel this hold"}</Text></Pressable>
                    </View>) if o.my_status == "claimed" and o.my_qr_payload else <StatusPill state={o.my_status} />}
                    <Text style={styles.claimPrice}>{money(o.my_price_cents / 100)}</Text>
                    <Text style={styles.claimBody}>{o.my_terms or "No additional terms."}</Text>
                    <Text style={styles.claimBody}>{"For: " + o.my_eligibility}</Text>
                    <Text style={styles.claimBody}>{"Hold expires " + o.my_expires + ". Unused holds release automatically."}</Text>
                </View>
            ) if o.my_claim_id else <View style={styles.hidden} />}
            <Message text={claimMsg} good={claimOk} />
            {(<Message text={"This offer is " + o.state + " right now."} good={False} />) if o.state != "active" and not hasSavedClaim else <View style={styles.hidden} />}
            <Pressable accessibilityRole="button" style={styles.btnGhost} disabled={busy} onPress={lambda { openOffer(o.id); }}><Text style={styles.btnGhostText}>Refresh offer and claim</Text></Pressable>
            <Pressable accessibilityRole="button"
                style={[styles.btn, {} if claimable and audience == "student" else styles.btnDisabled]}
                disabled={not claimable or busy or audience == "business"}
                onPress={lambda { changeClaim(False); }}
            >
                <Text style={styles.btnText}>
                    {"For U-M customers" if audience == "business" else "Updating..." if busy else "Sign in to claim" if not studentSession and claimable else "Claim this sample" if claimable and o.is_demo else "Claim this offer" if claimable else "Already claimed" if o.my_status else "Not claimable right now"}
                </Text>
            </Pressable>
            <Text style={styles.small}>Prices exclude tax unless the saved terms say otherwise. The restaurant checks the stated ID requirement.</Text>
            {AccessContext(o)}
            {(
                <View style={styles.note}>
                    <Text style={[styles.noteText, {"fontWeight": "800"}]}>Unverified restaurant note</Text>
                    <Text style={styles.noteText}>{o.entrance_note}</Text>
                    <Text style={styles.noteText}>{("Date provided: " + o.note_date + ". " if o.note_date else "") + "Not independently checked. Confirm current access with the restaurant."}</Text>
                </View>
            ) if o.entrance_note else <View style={styles.hidden} />}
            <View style={{"gap": 4}}>
                <Text style={styles.label}>Where</Text>
                <Text style={styles.body}>{o.address + (" · " + o.neighborhood if o.neighborhood else "")}</Text>
                {(<View style={{"gap": 4}}>
                    <Text style={styles.small}>{"For: " + o.eligibility}</Text>
                    <Text style={styles.small}>{o.terms or "No additional terms."}</Text>
                </View>) if not hasSavedClaim else <View style={styles.hidden} />}
            </View>
            {(<WhatNow key={o.my_claim_id} offerId={o.id} load={nearby_after} onOpenDeal={openOffer} />) if o.my_claim_id and o.my_status == "redeemed" else <View />}
        </View>;
    }

    def Editor() -> JsxElement {
        return <View style={styles.section}>
            <OfferEditor key={eId or "new"} initial={{
                "offer_id": eId, "title": eTitle, "description": eDesc,
                "price": ePrice, "regular_price": eRegular, "start_local": eStart,
                "end_local": eEnd, "quantity": eQty, "eligibility": eElig,
                "terms": eTerms, "dietary": eDiets, "menu_item": eItem, "image_url": ePhoto
            }} draftOwner={session.actor_id if session else ""} onDraftChange={updateOfferDraft} onBusyChange={setEditorBusy} saveOffer={save_offer} onSaved={afterOfferSaved} onCancel={lambda { editing = False; }} />
        </View>;
    }

    def Merchant() -> JsxElement {
        if not session or session.role != "merchant" { return <View style={styles.content}><MerchantGate /></View>; }
        return <View style={styles.content}>
            <View style={styles.header}>
                <Text style={styles.title}>Business offers</Text>
            </View>
            <View style={{"flexDirection": "row", "gap": 8}}>
            <Pressable accessibilityRole="button" style={[styles.btnGhost, {"paddingVertical": 8, "flex": 1}]} disabled={busy or editing} onPress={lambda { openBusiness(""); }}><Text style={styles.btnGhostText}>View business page</Text></Pressable>
            <Pressable accessibilityRole="button" style={[styles.btnGhost, {"paddingVertical": 8, "flex": 1}]} disabled={mLoading or busy or editing or profileEditing} onPress={lambda { openMerchant(); }}><Text style={styles.btnGhostText}>Refresh restaurant</Text></Pressable>
            </View>
            <Message text={mMsg} good={mOk} />
            {(
                <View style={styles.empty}><Text style={styles.subtitle}>Loading restaurant...</Text></View>
            ) if mLoading else (<View style={styles.hidden} />) if portal is None else <View style={{"gap": 16}}>
                {Editor() if editing else <View style={styles.hidden} />}
                <View style={styles.section}>
                    <View style={styles.rowBetween}>
                        <Text style={styles.h2}>Your offers</Text>
                        <Pressable accessibilityRole="button" style={styles.btn} disabled={editing or busy or profileEditing} onPress={lambda { newOffer(); }}>
                            <Text style={styles.btnText}>New offer</Text>
                        </Pressable>
                    </View>
                    {(<Text style={styles.small}>No offers yet. Create your first one.</Text>) if not portal.offers else <View style={styles.hidden} />}
                    {[
                        <View key={o.id} style={styles.card}>
                            {(<OfferImage url={o.offer_image_url} width={72} height={56} alt={o.title}/>) if o.offer_image_url else <View style={styles.hidden}/>}
                            <View style={styles.rowBetween}>
                                <Text style={[styles.offerTitle, styles.flex1]}>{o.title}</Text>
                                <StatusPill state={o.state} />
                            </View>
                            <Text style={styles.body}>{money(o.price) + "  ·  " + o.time_label}</Text>
                            <Text style={styles.small}>{str(o.remaining) + " of " + str(o.quantity) + " available"}</Text>
                            <View style={styles.row}>
                                <Pressable accessibilityRole="button" style={styles.btnGhost} disabled={editing or busy or profileEditing} onPress={lambda { editOffer(o); }}>
                                    <Text style={styles.btnGhostText}>Edit</Text>
                                </Pressable>
                                {(<Pressable accessibilityRole="button" style={styles.btnGhost} disabled={editing or busy or profileEditing} onPress={lambda { toggleStatus(o); }}>
                                    <Text style={styles.btnGhostText}>{"Resume" if o.state == "paused" else "Pause"}</Text>
                                </Pressable>) if o.state != "expired" else <View style={styles.hidden} />}
                            </View>
                        </View>
                        for o in portal.offers if o.state != "expired"
                    ]}
                    {(<details><summary style={{"padding": "12px 0", "cursor": "pointer", "fontWeight": 700}}>{"Past offers (" + str(len([o for o in portal.offers if o.state == "expired"])) + ")"}</summary><div style={{"display": "flex", "flexDirection": "column", "gap": 12}}>{[<div key={o.id} style={{"display": "flex", "alignItems": "center", "gap": 12, "paddingTop": 12, "borderTop": "1px solid var(--ml-border)"}}><div style={{"flex": 1, "minWidth": 0}}><strong>{o.title}</strong><div style={{"fontSize": 13, "color": "var(--ml-muted)", "marginTop": 4}}>{money(o.price) + " · " + o.time_label}</div></div><button type="button" disabled={editing or busy or profileEditing} onClick={lambda { editOffer(o); }} style={{"padding": 12, "minHeight": 44, "border": "1px solid var(--ml-border)", "borderRadius": 8, "background": "var(--ml-surface)", "color": "var(--ml-ink)", "cursor": "pointer"}}>Edit</button></div> for o in portal.offers if o.state == "expired"]}</div></details>) if len([o for o in portal.offers if o.state == "expired"]) > 0 else <View style={styles.hidden}/>}
                </View>
                <View style={styles.section}>
                    <Text style={styles.h2}>Restaurant profile</Text>
                    <View style={styles.row}>
                        {(<OfferImage url={portal.image_url} width={64} height={64} fit="contain" alt={portal.name} />) if portal.image_url else <View style={styles.hidden} />}
                        <Text style={[styles.restaurant, styles.flex1]}>{portal.name}</Text>
                    </View>
                    <Text style={styles.body}>{portal.address}</Text>
                    {(<View style={{"gap": 12}}>
                    <PhotoPicker label="Business photo" value={pPhoto} uploadPhoto={upload_business_photo} importPhoto={import_business_photo} importWebsite={import_business_website} onChange={lambda (picked: str) { pPhoto = picked; }} onBusyChange={setEditorBusy} disabled={busy}/>
                    <Text style={styles.muted}>Name and address changes need host review.</Text>
                    <Field label="Name" value={pName} onChange={lambda (t: str) { pName = t; }} placeholder="Restaurant name" multiline={False} disabled={True} />
                    <Field label="Cuisine" value={pCuisine} onChange={lambda (t: str) { pCuisine = t; }} placeholder="Noodles" multiline={False} disabled={busy} />
                    <Field label="About" value={pBlurb} onChange={lambda (t: str) { pBlurb = t; }} placeholder="Short description" multiline={True} disabled={busy} />
                    <Field label="Address" value={pAddress} onChange={lambda (t: str) { pAddress = t; }} placeholder="Street address" multiline={False} disabled={True} />
                    <Field label="Neighborhood" value={pHood} onChange={lambda (t: str) { pHood = t; }} placeholder="Kerrytown" multiline={False} disabled={busy} />
                    <Field label="Entrance or construction note" value={pNote} onChange={lambda (t: str) { pNote = t; }} placeholder="Use the side door while sidewalk work continues" multiline={True} disabled={busy} />
                    <Field label="Note date" value={pNoteDate} onChange={lambda (t: str) { pNoteDate = t; }} placeholder="2026-09-26" multiline={False} disabled={busy} />
                    <Pressable accessibilityRole="button" style={styles.btn} disabled={busy} onPress={lambda { saveProfile(); }}>
                        <Text style={styles.btnText}>{"Saving..." if busy else "Save profile"}</Text>
                    </Pressable>
                    <Pressable accessibilityRole="button" style={styles.btnGhost} disabled={busy} onPress={lambda { if portal is not None { fillProfile(portal); mMsg = ""; profileEditing = False; } }}>
                        <Text style={styles.btnGhostText}>Cancel profile changes</Text>
                    </Pressable>
                    </View>) if profileEditing else <Pressable accessibilityRole="button" style={styles.btnGhost} disabled={busy or editing} onPress={lambda { if session and session.business_account { goTab("account"); } else { profileEditing = True; } }}><Text style={styles.btnGhostText}>Edit business details</Text></Pressable>}
                </View>
            </View>}
        </View>;
    }

    def Redeem() -> JsxElement {
        if not session or session.role != "merchant" { return <View style={styles.content}><MerchantGate /></View>; }
        return <View style={styles.content}>
            <View style={styles.header}>
                <View style={styles.rowBetween}>
                    <Text style={styles.brand}>COUNTER</Text>
                </View>
                <Text style={styles.title}>Scan a claim</Text>
                <Text style={styles.subtitle}>Review the saved offer before redeeming.</Text>
            </View>
            <Message text={mMsg} good={mOk} />
            <Pressable accessibilityRole="button" style={styles.btnGhost} disabled={mLoading} onPress={lambda { openMerchant(); }}><Text style={styles.btnGhostText}>Refresh restaurant</Text></Pressable>
            {(<Text style={styles.small}>Loading your restaurant...</Text>) if mLoading else <View style={styles.hidden} />}
            {(<View style={styles.hidden} />) if portal is None else <View style={{"gap": 16}}>
                <View style={styles.section}>
                    <Text style={styles.restaurant}>{portal.name}</Text>
                    <ClaimScanner key={session.actor_id} resolveClaim={resolve_claim} redeemClaim={redeem_claim} onRedeemed={afterRedeemed} />
                </View>
                <View style={styles.section}>
                    <Text style={styles.h2}>Recent claims</Text>
                    {(<Text style={styles.small}>No claims yet.</Text>) if not portal.claims else <View style={styles.hidden} />}
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

    def Insights() -> JsxElement {
        if not session or session.role != "merchant" { return <View style={styles.content}><MerchantGate /></View>; }
        return <View style={styles.content}>
            <View style={styles.rowBetween}><Text style={styles.brand}>{"LOCAL ACTIVITY" if localActivity and session.catalog_activity else "YOUR BUSINESS"}</Text></View>
            {(<View style={styles.row}>
                <Pressable accessibilityRole="button" style={styles.btnGhost} onPress={lambda { localActivity = False; }}><Text style={styles.btnGhostText}>Your business</Text></Pressable>
                <Pressable accessibilityRole="button" style={styles.btnGhost} onPress={lambda { localActivity = True; }}><Text style={styles.btnGhostText}>Explore local activity</Text></Pressable>
            </View>) if session.catalog_activity else <View style={styles.hidden} />}
            <BusinessInsights key={session.actor_id + ("-local" if localActivity and session.catalog_activity else "-own")} getInsights={local_activity if localActivity and session.catalog_activity else merchant_insights} showProvenance={False if localActivity and session.catalog_activity else True} />
        </View>;
    }

    def TabButton(id: str, label: str) -> JsxElement {
        on = bool(tab == id or (id == "merchant" and tab == "discover" and session and session.role == "merchant"));
        return <Pressable accessibilityRole="button" accessibilityState={{"selected": on}} style={[styles.tab, styles.tabOn if on else {}]} disabled={busy} onPress={lambda { goTab(id); }}>
            <NavIcon name={id} active={on} />
            <Text style={[styles.tabText, styles.tabTextOn if on else {}]}>{label}</Text>
        </Pressable>;
    }

    if not sessionReady {
        return <View style={[styles.screen, {"height": viewport.height}]}><UiFoundation /><View style={styles.empty}><Text style={styles.subtitle}>Opening M-Local...</Text></View></View>;
    }
    if not audience {
        return <View style={[styles.screen, {"height": viewport.height}]}><UiFoundation /><AudienceWelcome onChoose={chooseAudience} /></View>;
    }

    signedIn: bool = session is not None and session.authenticated;
    role: str = session.role if session is not None and session.authenticated else "guest";
    company: bool = role in ["business", "merchant"];

    if not signedIn and (audience != "student" or authOpen) {
        return <View style={[styles.screen, {"height": viewport.height}]}>
            <UiFoundation />
            <View style={styles.frame}>
                <ScrollView style={[styles.scroll, {"height": viewport.height}]}>{AuthScreen()}</ScrollView>
            </View>
        </View>;
    }

    shown = tab;
    if role == "business" { shown = "account"; }
    elif role == "merchant" and tab == "discover" { shown = "merchant"; }
    elif not company and tab in ["merchant", "redeem", "insights"] { shown = "discover"; }

    body = (
        <BusinessProfile key={str(sessionEpoch.current) + profileSlug + profileOfferId} slug={profileSlug} offerId={profileOfferId} getProfile={get_business_profile}
            onBack={lambda { profileOpen = False; }} backLabel={"Back to offer" if selected else "Back to offers" if shown == "merchant" else "Back to offers"}
            canOpenOffers={not company} onOffer={lambda (oid: str) { profileOpen = False; openOffer(oid); }} /> if profileOpen
        else AccountScreen() if shown == "account"
        else (Detail() if selected else Discover()) if shown == "discover"
        else Insights() if shown == "insights" else Merchant() if shown == "merchant" else Redeem()
    );

    return <View style={[styles.screen, {"height": viewport.height}]}>
        <UiFoundation />
        <View style={[styles.frame, {"maxWidth": 1040} if shown == "insights" else {}]}>
            <ScrollView style={[styles.scroll, {"height": viewport.height}]}>
                <View testID="app-masthead" style={styles.masthead}><BrandLogo />{LogoutLink()}</View>
                {body}
            </ScrollView>
            {(
                <View testID="app-tabbar" style={styles.tabbar}>
                    {TabButton("discover", "Offers") if not company else <View style={styles.hidden} />}
                    {TabButton("merchant", "Offers") if role == "merchant" else <View style={styles.hidden} />}
                    {TabButton("redeem", "Scan QR") if role == "merchant" else <View style={styles.hidden} />}
                    {TabButton("insights", "Insights") if role == "merchant" else <View style={styles.hidden} />}
                    {TabButton("account", "Account")}
                </View>
            ) if signedIn and role != "business" else <View style={styles.hidden} />}
        </View>
    </View>;
}

