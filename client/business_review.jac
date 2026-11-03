"""Operator review of one business submission, opened from the emailed link."""
import from "react" { useEffect }
import from .ui { formStack, formInput, formButton, formSecondary, formHint }
import type from ..services.business_review_link { ReviewLinkView }

glob stack = formStack, inputStyle = formInput, primary = formButton, secondary = formSecondary, hint = formHint;

def:pub BusinessReview(
    token: str,
    getDetails: Callable[[str], ReviewLinkView],
    approve: Callable[[str, str], ReviewLinkView],
    onDone: Callable[[], None]
) -> JsxElement {
    has view: ReviewLinkView | None = None,
        loading: bool = True, busy: bool = False,
        note: str = "", message: str = "", failed: bool = False,
        mounted: Ref[bool] = Ref(False);

    async def load {
        loading = True;
        try {
            reply = await getDetails(token);
            if not mounted.current { return; }
            view = reply;
            failed = not reply.ok;
            message = reply.message;
        } except Exception {
            if mounted.current { failed = True; message = "Could not load this review. Check your connection and retry."; }
        } finally {
            if mounted.current { loading = False; }
        }
    }

    useEffect(lambda {
        mounted.current = True;
        load();
        return lambda { mounted.current = False; };
    }, []);

    async def confirm(event: FormEvent) {
        event.preventDefault();
        if busy { return; }
        busy = True;
        try {
            reply = await approve(token, note);
            if not mounted.current { return; }
            failed = not reply.ok;
            message = reply.message;
            if reply.ok { view = reply; }
        } except Exception {
            if mounted.current { failed = True; message = "Could not approve. Nothing changed; check your connection and retry."; }
        } finally {
            if mounted.current { busy = False; }
        }
    }

    return <main aria-label="Business review" style={{**stack, "maxWidth": 560, "margin": "0 auto", "padding": "32px 16px"}}>
        <h1 style={{"fontSize": 26, "margin": 0}}>Review a business</h1>
        {(<p role="status" style={hint}>Loading the submission...</p>) if loading else (
            <form style={stack} onSubmit={confirm} noValidate={True}>
                <dl style={{**stack, "gap": 8, "margin": 0}}>
                    <div><dt style={hint}>Business name</dt><dd style={{"margin": 0, "fontSize": 18, "fontWeight": 700}}>{view.name}</dd></div>
                    <div><dt style={hint}>Address</dt><dd style={{"margin": 0}}>{view.address}</dd></div>
                    {(<div><dt style={hint}>Account email</dt><dd style={{"margin": 0, "overflowWrap": "anywhere"}}>{view.email}</dd></div>) if view.email else None}
                    {(<div><dt style={hint}>Website</dt><dd style={{"margin": 0, "overflowWrap": "anywhere"}}>{view.website}</dd></div>) if view.website else None}
                    {(<div><dt style={hint}>Description</dt><dd style={{"margin": 0}}>{view.description}</dd></div>) if view.description else None}
                </dl>
                {(<p style={hint}>Approve only if this person can speak for the business at this address.</p>) if not view.approved else None}
                {(<label style={{**stack, "gap": 6, "fontSize": 14, "fontWeight": 600}}>
                    How you checked (optional)<input style={inputStyle} placeholder="For example: called the cafe" value={note} maxLength={500} disabled={busy} onChange={lambda (e: ChangeEvent) { note = e.target.value; }} />
                </label>) if not view.approved else None}
                {(<button style={primary} disabled={busy}>{"Approving..." if busy else "Approve this business"}</button>) if not view.approved else None}
            </form>
        ) if view is not None and view.ok else None}
        {(<p role={"alert" if failed else "status"} aria-live="polite" style={{**hint, "color": "var(--ml-bad)" if failed else "var(--ml-accent)"}}>{message}</p>) if message else None}
        <button style={secondary} type="button" onClick={lambda { onDone(); }}>Open M-Local</button>
    </main>;
}
