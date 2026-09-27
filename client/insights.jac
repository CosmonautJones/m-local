"""Private merchant analytics with replay, request isolation, and aggregate recap export."""

import from "react" { useEffect }
import from .ui { uiFont }
import from "./insights-support.mjs" {
    PERIODS, normalizeInsights, selectCutoff, chartSeries, money, count,
    displayDate, createRequestGate, buildRecapHtml, salesChart, salesPeak
}


obj InsightMetrics {
    has claims: int, redemptions: int, unique_customers: int,
        returning_customers: int, value_cents: int, savings_cents: int,
        savings_known: int, cohort_redeemed: int, cancelled: int, expired: int,
        pending: int, unknown_outcomes: int;
}

obj InsightOffer {
    has title: str, redemptions: int, value_cents: int;
}

obj InsightFrame {
    has day: int, date: str, daily: InsightMetrics, totals: InsightMetrics,
        offers: list[InsightOffer];
}

obj SalesBlock {
    has key: str, label: str, hours: str;
}

obj SalesOfferBlock {
    has key: str, label: str, claims: int, redemptions: int, value_cents: int;
}

obj SalesOffer {
    has title: str, schedule: str, claims: int, redemptions: int,
        value_cents: int, busiest: str, blocks: list[SalesOfferBlock];
}

obj InsightSales {
    has blocks: list[SalesBlock], days: list[any], offers: list[SalesOffer];
}

obj SalesBar {
    has day: int, date: str, value: int, redemptions: int, discount: int,
        known: int, regular: int, live: bool, x: float, width: float,
        y: float, height: float, extra: float, top: float, slot: float,
        slot_width: float, center: float;
}

obj SalesChartData {
    has key: str, maximum: int, bars: list[SalesBar], shown: int,
        value_cents: int, redemptions: int, discount_cents: int,
        discount_known: int, regular_cents: int, best_date: str,
        best_value_cents: int;
}

obj InsightData {
    has business_name: str, is_demo: bool, period_days: int, timezone: str,
        start_date: str, end_date: str, as_of: float, coverage_start_date: str,
        warnings: list[str], frames: list[InsightFrame],
        sales: InsightSales | None = None;
}

obj InsightRate {
    has denominator: int, percent: int | None;
}

obj InsightSelection {
    has index: int, frame: InsightFrame, history: list[InsightFrame],
        rate: InsightRate, first: InsightFrame | None,
        busiest: InsightFrame | None, top: InsightOffer | None;
}

obj InsightPoint {
    has day: int, value: int, x: float, y: float;
}

obj InsightSeries {
    has maximum: int, points: list[InsightPoint];
}

obj InsightGate {
    has begin: Callable[[], int], invalidate: Callable[[], None],
        accepts: Callable[[int], bool];
}

glob insightStyles: str = """.bi-metric{padding:18px;border:1px solid var(--ml-border);border-radius:16px;background:var(--ml-surface);min-width:0}.bi-metric:first-child{border-top:4px solid var(--ml-maize);padding-top:15px}.bi .bi-metrics{gap:12px}.bi .bi-timeline{border-radius:20px}.bi .bi-metric strong{font-weight:800}
.bi{--bi-ink:var(--ml-ink);--bi-muted:var(--ml-muted);--bi-orange:var(--ml-accent);--bi-rule:var(--ml-border);--bi-paper:var(--ml-surface);color:var(--bi-ink);font:14px/1.5 Figtree,system-ui,sans-serif;min-width:0;padding:8px 0 24px}.bi *{box-sizing:border-box}.bi button,.bi select{font:700 13px Figtree,system-ui;min-height:42px;border:1px solid var(--bi-rule);border-radius:8px;background:var(--bi-paper);color:var(--bi-ink);padding:8px 13px;cursor:pointer}.bi button:hover:not(:disabled){border-color:var(--ml-accent)}.bi button:disabled{opacity:.5;cursor:default}.bi button:focus-visible,.bi select:focus-visible,.bi input:focus-visible,.bi summary:focus-visible{outline:3px solid var(--ml-focus);outline-offset:3px}.bi .bi-primary{background:var(--bi-orange);color:var(--ml-accent-text);border-color:var(--bi-orange)}.bi-header{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;flex-wrap:wrap;border-bottom:1px solid var(--bi-rule);padding-bottom:20px}.bi-eyebrow{font-size:11px;letter-spacing:.12em;text-transform:uppercase;font-weight:800;color:var(--bi-orange);margin:0 0 8px}.bi h2{font:800 clamp(29px,4vw,38px)/1.1 Figtree,system-ui;margin:0 0 8px}.bi h3{font-size:16px;margin:0 0 12px;letter-spacing:-.01em}.bi p{margin:0}.bi-note{color:var(--bi-muted);font-size:12px;line-height:1.55}.bi-toolbar{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;margin:20px 0}.bi-periods{display:flex;gap:4px;flex-wrap:wrap;padding:4px;background:var(--ml-sunken);border-radius:10px}.bi-periods button{border-color:transparent;background:transparent;min-height:38px;padding:8px 12px}.bi-periods button[aria-pressed=true]{background:var(--ml-accent);color:var(--ml-accent-text);box-shadow:0 1px 3px var(--ml-shadow)}.bi-actions{display:flex;gap:8px;flex-wrap:wrap}.bi-badge{display:inline-block;border:1px solid var(--ml-border);padding:3px 8px;border-radius:20px;font-size:11px;font-weight:700;color:var(--ml-warn);margin-bottom:6px}.bi-metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;padding:8px 0 26px}.bi-metric strong{display:block;font-size:clamp(28px,3.7vw,40px);line-height:1.2;letter-spacing:-.045em;font-weight:650;font-variant-numeric:tabular-nums;margin:4px 0 8px;overflow-wrap:anywhere}.bi-metric h3{font-size:12px;line-height:1.4;color:var(--bi-muted);font-weight:600;margin:0}.bi-timeline{padding:22px;background:var(--bi-paper);border:1px solid var(--bi-rule);border-radius:14px}.bi-timeline-top{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap}.bi-timeline h3{font:800 24px/1.2 Figtree,system-ui;margin-bottom:5px}.bi-chart{width:100%;height:auto;display:block;overflow:visible;margin:8px 0}.bi-chart-meta{display:flex;justify-content:space-between;gap:12px;font-size:11px;color:var(--bi-muted)}.bi-chart-toggle{display:flex;gap:3px}.bi-chart-toggle button{font-size:11px;padding:6px 10px;min-height:34px}.bi-chart-toggle button[aria-pressed=true]{color:var(--bi-orange);background:var(--ml-accent-soft);border-color:var(--ml-accent)}.bi-seek{width:100%;accent-color:var(--bi-orange);min-height:32px;margin:12px 0 6px;cursor:pointer}.bi-transport{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.bi-transport .bi-progress{margin-left:auto;font-variant-numeric:tabular-nums}.bi-snapshot{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;font-size:12px;color:var(--bi-muted);margin:12px 0 22px}.bi-columns{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:32px;padding:4px 0 20px}.bi-outcome{margin-bottom:12px}.bi-outcome-line{display:flex;gap:8px;justify-content:space-between;font-size:12px;margin-bottom:6px}.bi-outcome-bar{height:7px;border-radius:5px;background:var(--ml-sunken);overflow:hidden}.bi-outcome-bar span{display:block;height:100%;border-radius:5px}.bi-rate{font-size:28px;line-height:1.2;font-weight:650;letter-spacing:-.035em;margin:0 0 12px}.bi-offers{list-style:none;margin:0;padding:0}.bi-offers li{display:flex;justify-content:space-between;gap:16px;padding:11px 0;border-bottom:1px solid var(--bi-rule)}.bi-offers li:first-child{padding-top:0}.bi-offer-title{font-size:13px;min-width:0;overflow-wrap:anywhere}.bi-offer-amount{text-align:right;white-space:nowrap;font-size:12px;font-variant-numeric:tabular-nums}.bi-offer-amount strong{display:block}.bi-story{border-top:1px solid var(--bi-rule);padding:22px 0}.bi-story blockquote{font:600 22px/1.45 Figtree,system-ui;margin:0 0 12px;max-width:760px}.bi-footer{border-top:1px solid var(--bi-rule);padding-top:16px}.bi-footer summary{cursor:pointer;font-size:12px;font-weight:650;min-height:32px}.bi-footer ul{padding-left:20px;font-size:12px;line-height:1.6;color:var(--bi-muted)}.bi-notice{padding:14px 16px;border:1px solid var(--ml-border);border-radius:10px;background:var(--ml-warn-soft);font-size:13px;margin:0 0 18px}.bi-error{border-color:var(--ml-bad);background:var(--ml-bad-soft);color:var(--ml-bad)}.bi-empty{padding:34px 22px;border:1px dashed var(--ml-border);border-radius:12px;text-align:center;margin-bottom:20px}.bi-empty h3{font:700 23px Figtree,system-ui,sans-serif;margin-bottom:10px}.bi-loading{padding:42px 18px;border-block:1px solid var(--bi-rule);color:var(--bi-muted)}.bi-sr{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}@media(max-width:620px){.bi-periods{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));width:100%}.bi-periods button{padding:8px 4px;white-space:nowrap}.bi-metrics{grid-template-columns:repeat(2,minmax(0,1fr));gap:22px 16px}.bi-columns{grid-template-columns:minmax(0,1fr);gap:26px}.bi-timeline{padding:16px}.bi-actions{width:100%}.bi-actions button{flex:1}.bi-story blockquote{font-size:22px}.bi-transport .bi-progress{width:100%;margin:3px 0 0}.bi-header h2{font-size:34px}}@media(prefers-reduced-motion:reduce){.bi *{scroll-behavior:auto;transition:none!important;animation:none!important}}
.bi-sales{display:grid;gap:16px;margin:20px 0}.bi-sales-grid{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(220px,1fr))}.bi-sales-chart{padding:16px;border:1px solid var(--ml-border);border-radius:16px;background:var(--ml-surface);min-width:0}.bi-sales-chart.bi-sales-all{border-top:4px solid var(--ml-maize)}.bi-sales-top{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;margin-bottom:8px}.bi-sales-top h3{margin:0}.bi-sales-total{text-align:right;display:flex;flex-direction:column;flex-shrink:0}.bi-sales-total strong{font-size:22px;font-weight:800;line-height:1.1}.bi-sales-offers li{align-items:flex-start}.bi-sales-offers .bi-offer-amount{display:flex;flex-direction:column;align-items:flex-end;text-align:right;flex-shrink:0}.bi-sales-offers .bi-note{display:block}
.bi-sales-plot{position:relative}.bi-sales-tip{position:absolute;top:0;transform:translateX(-50%);z-index:2;pointer-events:none;min-width:150px;max-width:210px;padding:8px 10px;border:1px solid var(--ml-border);border-radius:10px;background:var(--ml-surface);box-shadow:0 6px 18px rgba(11,31,56,.16);font-size:12px;line-height:1.45;color:var(--ml-ink)}.bi-sales-tip strong{display:block;font-size:13px}.bi-sales-tip span{display:block}.bi-bar-hit{cursor:pointer;outline:none}.bi-bar-hit:focus-visible{stroke:var(--ml-accent);stroke-width:2}.bi-sales-key{display:flex;gap:14px;flex-wrap:wrap;font-size:12px;color:var(--ml-muted)}.bi-sales-key i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px;vertical-align:-1px}.bi-sales-cost{padding:16px;border:1px solid var(--ml-border);border-top:4px solid var(--ml-maize);border-radius:16px;background:var(--ml-surface)}.bi-sales-cost strong{display:block;font-size:26px;font-weight:800;line-height:1.15;margin:4px 0}
""";


def RedemptionChart(data: InsightData, cutoff: int, mode: str) -> JsxElement {
    series = chartSeries(data, cutoff, mode) as InsightSeries;
    points = " ".join([str(point.x) + "," + str(point.y) for point in series.points]);
    last = series.points[-1];
    chartLabel = ("Daily" if mode == "daily" else "Cumulative") + " redemptions through " + (
        displayDate(data.frames[cutoff].date) if cutoff else "the start of the period"
    );
    barWidth = min(12.0, 560 / data.period_days);
    return <>
        <svg className="bi-chart" viewBox="0 0 720 174" role="img" aria-label={chartLabel}>
            {[<line key={y} x1="12" x2="708" y1={y} y2={y} stroke="var(--ml-border)" strokeDasharray={None if y == 154 else "3 5"} /> for y in [22, 88, 154]]}
            {(<>
                <polygon points={"12,154 " + points + " " + str(last.x) + ",154"} fill="var(--ml-accent)" fillOpacity="0.07" />
                <polyline points={points} fill="none" stroke="var(--ml-accent)" strokeWidth="2.7" strokeLinecap="round" strokeLinejoin="round" />
                <circle cx={last.x} cy={last.y} r="4" fill="var(--ml-accent)" />
            </>) if mode == "cumulative" else [
                <rect key={point.day} x={point.x - barWidth / 2} y={point.y} width={barWidth} height={154 - point.y} rx="1" fill="var(--ml-accent)" />
                for point in series.points[1:]
            ]}
        </svg>
        <div className="bi-chart-meta"><span>{displayDate(data.start_date)}</span><span>{"0–" + count(series.maximum) + " redemptions"}</span><span>{displayDate(data.end_date)}</span></div>
    </>;
}


def SalesChart(
    data: InsightData, sales: InsightSales, part: str, title: str, hours: str,
    cutoff: int, ceiling: int
) -> JsxElement {
    has picked: int = 0;

    chart = salesChart(sales, part, cutoff, ceiling) as SalesChartData;
    spoken = title + " sales through your offers: " + money(chart.value_cents) + " from " + count(chart.redemptions) + " redemptions";
    chosen = [bar for bar in chart.bars if bar.day == picked and bar.live];
    return <section className={"bi-sales-chart" + (" bi-sales-all" if part == "total" else "")} data-part={part} aria-label={title + " sales"}>
        <div className="bi-sales-top">
            <div><h3>{title}</h3><p className="bi-note">{hours}</p></div>
            <div className="bi-sales-total"><strong>{money(chart.value_cents)}</strong><span className="bi-note">{count(chart.redemptions) + " redeemed"}</span>{(<span className="bi-note">{money(chart.regular_cents) + " at regular prices"}</span>) if chart.discount_known > 0 else None}</div>
        </div>
        <div className="bi-sales-plot" onMouseLeave={lambda { picked = 0; }}>
            {(<div className="bi-sales-tip" role="status" style={{"left": str(min(80.0, max(20.0, chosen[0].center))) + "%"}}>
                <strong>{displayDate(chosen[0].date, True)}</strong>
                <span>{money(chosen[0].value) + " in redemptions"}</span>
                <span>{count(chosen[0].redemptions) + (" redemption" if chosen[0].redemptions == 1 else " redemptions")}</span>
                {(<span>{money(chosen[0].regular) + " at regular prices, " + money(chosen[0].discount) + " discounted"}</span>) if chosen[0].known > 0 else None}
            </div>) if chosen else None}
            <svg className="bi-chart" viewBox="0 0 720 146" role="img" aria-label={spoken}>
                {[<line key={y} x1="12" x2="708" y1={y} y2={y} stroke="var(--ml-border)" strokeDasharray={None if y == 132 else "3 5"} /> for y in [12, 72, 132]]}
                {[
                    <rect className="bi-bar-discount" key={"d" + str(bar.day)} x={bar.x} y={bar.top} width={bar.width} height={bar.extra} rx="1" fill="var(--ml-maize)" />
                    for bar in chart.bars if bar.extra > 0
                ]}
                {[
                    <rect className="bi-bar-paid" key={"p" + str(bar.day)} x={bar.x} y={bar.y} width={bar.width} height={bar.height} rx="1" fill="var(--ml-accent)" />
                    for bar in chart.bars if bar.height > 0
                ]}
                {[
                    <rect className="bi-bar-hit" key={"h" + str(bar.day)} data-day={bar.day} x={bar.slot} y="8" width={bar.slot_width} height="126" fill="transparent" tabIndex={0} role="button"
                        aria-label={displayDate(bar.date, True) + ": " + money(bar.value) + " in redemptions, " + count(bar.redemptions) + (" redemption" if bar.redemptions == 1 else " redemptions")}
                        onMouseEnter={lambda { picked = bar.day; }} onFocus={lambda { picked = bar.day; }} onClick={lambda { picked = bar.day; }} onBlur={lambda { picked = 0; }} />
                    for bar in chart.bars if bar.live
                ]}
            </svg>
        </div>
        <div className="bi-chart-meta"><span>{displayDate(data.start_date)}</span><span>{"Top of chart: " + money(chart.maximum)}</span><span>{displayDate(data.end_date)}</span></div>
        <p className="bi-note">{("Best day: " + displayDate(chart.best_date) + " with " + money(chart.best_value_cents) + ". Point at a bar for that day.") if chart.best_date else "No redemptions recorded here yet."}</p>
    </section>;
}


def SalesCharts(data: InsightData, cutoff: int) -> JsxElement {
    sales = data.sales;
    if sales is None {
        return <></>;
    }
    peak = salesPeak(sales, cutoff) as int;
    whole = salesChart(sales, "total", cutoff, 0) as SalesChartData;
    return <section className="bi-sales" aria-label="Sales through your offers">
        <div>
            <h3>Sales through your offers</h3>
            <p className="bi-note">The recorded price of every redeemed offer, by day, in Ann Arbor time. The four time-of-day charts share one scale so they can be compared. Extras bought in store are not recorded.</p>
            <p className="bi-sales-key"><span><i style={{"background": "var(--ml-accent)"}} />Paid with your offers</span><span><i style={{"background": "var(--ml-maize)"}} />Lost potential: what regular prices would have added</span></p>
        </div>
        <SalesChart data={data} sales={sales} part="total" title="All day" hours="Every redemption" cutoff={cutoff} ceiling={0} />
        <div className="bi-sales-grid">
            {[
                <SalesChart key={block.key} data={data} sales={sales} part={block.key} title={block.label} hours={block.hours} cutoff={cutoff} ceiling={peak} />
                for block in sales.blocks
            ]}
        </div>
        <div className="bi-sales-cost" aria-label="Total subsidized through discounts">
            <h3>Total subsidized through discounts</h3>
            {(<>
                <strong>{money(whole.discount_cents)}</strong>
                <p className="bi-note">{money(whole.discount_cents) + " in recorded discounts across " + count(whole.discount_known) + " redemptions with a known regular price."}</p>
                <p className="bi-note">{"This is what your business gave up through its discounts, its total losses against regular prices. At regular prices these redemptions would have brought in " + money(whole.regular_cents) + "; with your offers they brought in " + money(whole.value_cents) + "."}</p>
                <p className="bi-note">It assumes every one of these customers would have paid full price without the offer.</p>
            </>) if whole.discount_known > 0 else <p className="bi-note">No redemption in this period has a recorded regular price, so the discount cannot be totaled.</p>}
        </div>
        {(<div>
            <h3>What each offer did, and when</h3>
            <p className="bi-note">The whole period, including dates beyond the replay date.</p>
            <ol className="bi-offers bi-sales-offers">{[
                <li key={str(index) + "-" + offer.title}>
                    <span className="bi-offer-title">
                        {offer.title}
                        {(<span className="bi-note">{"Current schedule: " + offer.schedule}</span>) if offer.schedule else None}
                        <span className="bi-note">{" · ".join([part.label + ": " + count(part.claims) + " claimed, " + count(part.redemptions) + " redeemed" for part in offer.blocks if part.claims or part.redemptions]) or "No activity in this period"}</span>
                    </span>
                    <span className="bi-offer-amount">
                        <strong>{count(offer.redemptions) + " redeemed"}</strong>
                        <span className="bi-note">{count(offer.claims) + " claimed · " + money(offer.value_cents)}</span>
                        {(<span className="bi-note">{"Busiest: " + offer.busiest}</span>) if offer.busiest else None}
                    </span>
                </li>
                for (index, offer) in enumerate(sales.offers[:8])
            ]}</ol>
        </div>) if len(sales.offers) else None}
    </section>;
}


def Outcomes(metrics: InsightMetrics, rate: InsightRate) -> JsxElement {
    outcomes: list[tuple[str, int, str]] = [
        ("Redeemed", metrics.cohort_redeemed, "var(--ml-accent)"),
        ("Cancelled", metrics.cancelled, "var(--ml-chart-cancelled)"),
        ("Expired", metrics.expired, "var(--ml-chart-expired)")
    ];
    return <section aria-label="Claim outcomes">
        <h3>What happened to claims</h3>
        <div className="bi-rate">{"No resolved claims" if rate.percent is None else str(rate.percent) + "% redeemed"}</div>
        <p className="bi-note" style={{"marginBottom": 16}}>{count(rate.denominator) + " resolved claims in this period."}</p>
        {[
            <div className="bi-outcome" key={label}>
                <div className="bi-outcome-line"><span>{label}</span><strong>{count(total)}</strong></div>
                <div className="bi-outcome-bar" aria-hidden="true"><span style={{"width": str(min(100.0, total / metrics.claims * 100) if metrics.claims else 0) + "%", "background": color}} /></div>
            </div>
            for (label, total, color) in outcomes
        ]}
    </section>;
}


"""The parent keys this component by the authenticated actor."""
def:pub BusinessInsights(getInsights: Callable[[int], any], showProvenance: bool = True) -> JsxElement {
    has period: int = 30,
        data: InsightData | None = None,
        cutoff: int = 0,
        loading: bool = True,
        refreshing: bool = False,
        error: str = "",
        frozen: bool = False,
        playing: bool = False,
        speed: int = 1,
        mode: str = "cumulative",
        exportError: str = "",
        mounted: Ref[bool] = Ref(False),
        api: Ref[Callable[[int], any]] = Ref(getInsights),
        gate: Ref[InsightGate] = Ref(createRequestGate() as InsightGate),
        frozenRef: Ref[bool] = Ref(False),
        periodRef: Ref[int] = Ref(30),
        cutoffRef: Ref[int] = Ref(0),
        loadRef: Ref[Callable[[bool], Awaitable[None]] | None] = Ref(None);

    requestGate = gate.current as InsightGate;
    browserDocument = document as any;
    browser = window as any;
    api.current = getInsights;
    periodRef.current = period;
    cutoffRef.current = cutoff;

    # Polling and visibility listeners share this exact effect's cleanup closure.
    useEffect(lambda {
        mounted.current = True; frozenRef.current = False;
        data = None; cutoff = 0; cutoffRef.current = 0;
        playing = False; frozen = False; loading = True; error = ""; exportError = "";
        requestedPeriod = period;
        activeRequest: int | None = None;

        async def load(background: bool = False) {
            if background and (browserDocument.hidden or frozenRef.current or activeRequest is not None) { return; }
            token = requestGate.begin();
            activeRequest = token;
            refreshing = True;
            try {
                reply = await (api.current as any).call(None, requestedPeriod);
                if not mounted.current or not requestGate.accepts(token) or periodRef.current != requestedPeriod { return; }
                clean = normalizeInsights(reply, requestedPeriod) as InsightData;
                data = clean; cutoff = clean.period_days; cutoffRef.current = clean.period_days; error = "";
            } except Exception as failure {
                if mounted.current and requestGate.accepts(token) and periodRef.current == requestedPeriod {
                    error = (failure as any).message as str if isinstance(failure, browser.Error) else "Insights could not be loaded. Check your connection and retry.";
                }
            } finally {
                if activeRequest == token { activeRequest = None; }
                if mounted.current and requestGate.accepts(token) and periodRef.current == requestedPeriod {
                    loading = False; refreshing = False;
                }
            }
        }

        loadRef.current = load;
        load();
        interval = setInterval(lambda { load(True); }, 30000);
        def visible() {
            if not browserDocument.hidden { load(True); }
            else { playing = False; }
        }
        document.addEventListener("visibilitychange", visible);
        return lambda {
            mounted.current = False; requestGate.invalidate(); clearInterval(interval);
            document.removeEventListener("visibilitychange", visible);
        };
    }, [period]);

    useEffect(lambda {
        if not playing or not data { return; }
        recording = data;
        def advance() {
            nextDay = min(recording.period_days, (cutoffRef.current or 0) + 1);
            cutoffRef.current = nextDay; cutoff = nextDay;
            if nextDay == recording.period_days { playing = False; }
        }
        interval = setInterval(advance, 150 / speed);
        return lambda { clearInterval(interval); };
    }, [playing, speed, data]);

    def freeze() {
        requestGate.invalidate(); frozenRef.current = True; frozen = True; refreshing = False;
    }
    def seek(day: int) {
        freeze(); playing = False; cutoffRef.current = day; cutoff = day;
    }
    def play() {
        if playing { playing = False; return; }
        if not data { return; }
        freeze();
        if cutoff >= data.period_days { cutoffRef.current = 0; cutoff = 0; }
        playing = True;
    }
    def latest() {
        playing = False; frozenRef.current = False; frozen = False; error = "";
        if loadRef.current { (loadRef.current as any).call(None, False); }
    }
    def downloadRecap() {
        exportError = "";
        if not data { return; }
        try {
            blob = new(browser.Blob, [buildRecapHtml(data, showProvenance)], {"type": "text/html;charset=utf-8"});
            url = browser.URL.createObjectURL(blob);
            anchor = browserDocument.createElement("a");
            anchor.href = url;
            anchor.download = "M-Local-" + str(period) + "-day-recap-" + data.end_date + ".html";
            browserDocument.body.appendChild(anchor); anchor.click(); anchor.remove();
            setTimeout(lambda { browser.URL.revokeObjectURL(url); }, 1000);
        } except Exception {
            exportError = "The recap could not be prepared. Refresh this period and try again.";
        }
    }
    def choosePeriod(days: int) {
        if days != period { requestGate.invalidate(); period = days; }
    }

    view = selectCutoff(data, cutoff) as InsightSelection if data else None;
    totals = view.frame.totals if view else None;
    empty = data and data.frames[-1].totals.claims == 0 and data.frames[-1].totals.redemptions == 0;
    collected = new(browser.Intl.DateTimeFormat, "en-US", {"hour": "numeric", "minute": "2-digit", "timeZone": "America/Detroit"}).format(new(Date, data.as_of * 1000)) as str if data else "";

    return <section className="bi" aria-label="Business insights" style={{"fontFamily": uiFont}}>
        <style>{insightStyles}</style>
        <header className="bi-header">
            <div><p className="bi-eyebrow">Business insights</p><h2>{"Your year in review" if period == 365 else "See your business in motion"}</h2><p className="bi-note">Recorded activity, one day at a time.</p></div>
            {(<div>{(<div className="bi-badge">Demo business · demo activity</div>) if data.is_demo and showProvenance else None}<p style={{"fontWeight": 650, "overflowWrap": "anywhere"}}>{data.business_name}</p></div>) if data else None}
        </header>
        <div className="bi-toolbar">
            <div className="bi-periods" role="group" aria-label="Insights period">
                {[<button type="button" key={days} aria-pressed={period == days} onClick={lambda { choosePeriod(days); }}>{"Year" if days == 365 else str(days) + " days"}</button> for days in PERIODS]}
            </div>
            <div className="bi-actions">
                <button type="button" onClick={latest} disabled={loading or refreshing}>{"Refreshing…" if refreshing else "Return to latest" if frozen else "Refresh"}</button>
                <button type="button" onClick={downloadRecap} disabled={not data or loading}>Download recap</button>
            </div>
        </div>
        {(<div className="bi-notice bi-error" role="alert">{error + " " + ("The last loaded recording is still shown." if data else "Use Refresh to try again.")}</div>) if error else None}
        {(<div className="bi-notice bi-error" role="alert">{exportError}</div>) if exportError else None}
        {(<div className="bi-loading" role="status">Loading your business’s recorded activity…</div>) if loading else None}
        {(<>
            {(<div className="bi-empty"><h3>Your next redemption starts the story.</h3><p className="bi-note">There are no recorded claims or redemptions in this period. Publish an offer, then return here as customers claim and redeem it.</p></div>) if empty else None}
            <div className="bi-metrics" aria-label={"Metrics through " + view.frame.date}>
                {[
                    <div className="bi-metric" key={label}><h3>{label}</h3><strong>{value}</strong><p className="bi-note">{note}</p></div>
                    for (label, value, note) in [
                        ("Claims", count(totals.claims), "Created in this period"),
                        ("Redemptions", count(totals.redemptions), "Completed in this period"),
                        ("Returning accounts", count(totals.returning_customers), "Redeemed on an earlier day"),
                        ("Redeemed offer value", money(totals.value_cents), "At the recorded claim price")
                    ]
                ]}
            </div>
            <section className="bi-timeline" aria-label="Activity replay">
                <div className="bi-timeline-top">
                    <div><h3>{displayDate(view.frame.date, True) if cutoff else "Before the first day"}</h3><p className="bi-note">{("Replay recording" if frozen else "Latest recording") + " · " + displayDate(data.start_date, data.start_date[:4] != data.end_date[:4]) + " to " + displayDate(data.end_date, True)}</p></div>
                    <div className="bi-chart-toggle" role="group" aria-label="Chart totals">
                        <button type="button" aria-pressed={mode == "cumulative"} onClick={lambda { mode = "cumulative"; }}>Cumulative</button>
                        <button type="button" aria-pressed={mode == "daily"} onClick={lambda { mode = "daily"; }}>Daily</button>
                    </div>
                </div>
                <RedemptionChart data={data} cutoff={cutoff} mode={mode} />
                <label className="bi-sr" htmlFor="bi-replay-date">Replay date</label>
                <input id="bi-replay-date" className="bi-seek" type="range" min="0" max={str(data.period_days)} step="1" value={cutoff} aria-valuetext={displayDate(view.frame.date, True) if cutoff else "Before the period begins"} onChange={lambda (event: ChangeEvent) { seek(int(event.target.value)); }} />
                <div className="bi-transport">
                    <button type="button" className="bi-primary" onClick={play}>{"Pause replay" if playing else "Replay this period" if cutoff == data.period_days else "Play"}</button>
                    <button type="button" onClick={lambda { seek(0); }}>Reset</button>
                    <label className="bi-sr" htmlFor="bi-replay-speed">Replay speed</label>
                    <select id="bi-replay-speed" value={str(speed)} onChange={lambda (event: ChangeEvent) { speed = int(event.target.value); }}><option value="1">1× speed</option><option value="3">3× speed</option><option value="8">8× speed</option></select>
                    <span className="bi-note bi-progress">{"Day " + str(cutoff) + " / " + str(data.period_days)}</span>
                </div>
            </section>
            <SalesCharts data={data} cutoff={cutoff} />
            <div className="bi-snapshot"><span>{"Updates paused while you explore. Return to latest to refresh." if frozen else "Refreshes every 30 seconds while this tab is visible."}</span><span>{"Collected " + collected + " · Ann Arbor time"}</span></div>
            <div className="bi-columns">
                <Outcomes metrics={totals} rate={view.rate} />
                <section aria-label="Most-redeemed offers">
                    <h3>Most-redeemed offers</h3>
                    {(<ol className="bi-offers">{[
                        <li key={str(index) + "-" + offer.title}><span className="bi-offer-title">{offer.title}</span><span className="bi-offer-amount"><strong>{count(offer.redemptions) + " redeemed"}</strong><span className="bi-note">{money(offer.value_cents) + " value"}</span></span></li>
                        for (index, offer) in enumerate(view.frame.offers[:5])
                    ]}</ol>) if len(view.frame.offers) else <p className="bi-note">Redeemed offers appear here as this period unfolds.</p>}
                    <p className="bi-note" style={{"marginTop": 16}}>{count(totals.unique_customers) + " distinct redeeming accounts so far."}</p>
                    {(<p className="bi-note" style={{"marginTop": 8}}>{money(totals.savings_cents) + " in recorded discounts across " + count(totals.savings_known) + " redemptions with a known regular price."}</p>) if totals.savings_known > 0 else None}
                </section>
            </div>
            <section className="bi-story" aria-label="Your period story">
                <p className="bi-eyebrow">Your story so far</p>
                <blockquote>{(displayDate(view.busiest.date) + " brought " + count(view.busiest.daily.redemptions) + " redemption" + ("" if view.busiest.daily.redemptions == 1 else "s") + ", your busiest day in this period so far.") if view.busiest else "The first recorded redemption will begin this story."}</blockquote>
                {(<p className="bi-note">{"The first redemption in this period was on " + displayDate(view.first.date) + "." + (" " + view.top.title + " leads with " + count(view.top.redemptions) + " redemptions through this date." if view.top else "")}</p>) if view.first else None}
            </section>
            <footer className="bi-footer">
                <details><summary>How these numbers are counted</summary><ul>
                    <li>Claims and outcomes follow claims created in the selected period. Redemptions and value follow redemption dates, including offers claimed before the period.</li>
                    <li>The redemption rate is redeemed claims divided by redeemed, cancelled, and expired claims.</li>
                    <li>A returning account redeemed at this business on an earlier Ann Arbor calendar date. Multiple redemptions on a first day do not create a returning account.</li>
                    <li>Redeemed offer value uses the price saved when the customer claimed the offer. It is not payment revenue. Discounts are included only when a regular price was recorded.</li>
                    <li>Sales through your offers is the same redeemed offer value, shown by day. Morning is 6 AM to 11 AM, lunch 11 AM to 4 PM, dinner 4 PM to 9 PM and late night 9 PM to 6 AM, in Ann Arbor time.</li>
                    <li>Views, nearby selections, and verified visits are not yet included. Customer identities and travel paths are not shown or exported.</li>
                    <li>Downloads include this entire recorded period, including dates beyond the replay cursor, and contain business-level aggregate metrics and offer titles.</li>
                    {(<li>{"Earliest supported activity: " + displayDate(data.coverage_start_date, True) + "."}</li>) if data.coverage_start_date else None}
                    {[<li key={index}>{warning}</li> for (index, warning) in enumerate(data.warnings)]}
                </ul></details>
                <p className="bi-note">Private business insights. Your downloaded recap contains aggregate results only.</p>
            </footer>
        </>) if data and view and totals and not loading else None}
    </section>;
}
