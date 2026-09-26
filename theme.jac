"""PromoPusher design tokens and stylesheet factory (React Native StyleSheet).

No JSX here: E1105 is only enforced on main.jac, so UI stays there.
"""

import from "@jac/mobui" { StyleSheet }


glob:pub C: dict[str, str] = {
         "bg": "#faf7f2",
         "surface": "#ffffff",
         "sunken": "#f3eee6",
         "border": "#e7dfd3",
         "ink": "#1d1a16",
         "text": "#3a342c",
         "muted": "#7a7064",
         "accent": "#d9480f",
         "accentSoft": "#fff0e6",
         "accentText": "#ffffff",
         "brand": "#1f3a5f",
         "good": "#2b8a3e",
         "goodSoft": "#e9f7ec",
         "warn": "#b35c00",
         "warnSoft": "#fff4db",
         "bad": "#c92a2a",
         "badSoft": "#fdecec"
     },
     S: dict[str, int] = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 20, "xxl": 28},
     R: dict[str, int] = {"sm": 8, "md": 12, "lg": 18, "pill": 999},
     F: dict[str, int] = {"xs": 12, "sm": 13, "md": 15, "lg": 18, "xl": 24, "xxl": 30};


def:pub buildStyles(T: dict[str, str]) -> any {
    return StyleSheet.create(
        {
            "screen": {"flex": 1, "backgroundColor": T["bg"]},
            "frame": {
                "flex": 1,
                "width": "100%",
                "maxWidth": 520,
                "alignSelf": "center",
                "backgroundColor": T["bg"]
            },
            "scroll": {"flex": 1},
            "content": {
                "paddingHorizontal": S["xl"],
                "paddingTop": S["xl"],
                "paddingBottom": 110,
                "gap": S["lg"]
            },
            "header": {"gap": S["xs"]},
            "brandRow": {
                "flexDirection": "row",
                "alignItems": "center",
                "justifyContent": "space-between"
            },
            "brand": {
                "fontSize": F["md"],
                "fontWeight": "800",
                "color": T["accent"],
                "letterSpacing": 0.5
            },
            "title": {
                "fontSize": F["xxl"],
                "fontWeight": "800",
                "color": T["ink"],
                "lineHeight": 36
            },
            "h2": {"fontSize": F["lg"], "fontWeight": "800", "color": T["ink"]},
            "subtitle": {"fontSize": F["md"], "color": T["muted"], "lineHeight": 21},
            "body": {"fontSize": F["md"], "color": T["text"], "lineHeight": 22},
            "small": {"fontSize": F["sm"], "color": T["muted"], "lineHeight": 19},
            "label": {
                "fontSize": F["xs"],
                "fontWeight": "700",
                "color": T["muted"],
                "textTransform": "uppercase",
                "letterSpacing": 0.8
            },
            "row": {"flexDirection": "row", "alignItems": "center", "gap": S["sm"]},
            "rowBetween": {
                "flexDirection": "row",
                "alignItems": "center",
                "justifyContent": "space-between",
                "gap": S["sm"]
            },
            "wrap": {"flexDirection": "row", "flexWrap": "wrap", "gap": S["sm"]},
            "card": {
                "backgroundColor": T["surface"],
                "borderRadius": R["lg"],
                "borderWidth": 1,
                "borderColor": T["border"],
                "padding": S["lg"],
                "gap": S["sm"]
            },
            "cardMuted": {"opacity": 0.6},
            "section": {
                "backgroundColor": T["surface"],
                "borderRadius": R["lg"],
                "borderWidth": 1,
                "borderColor": T["border"],
                "padding": S["lg"],
                "gap": S["md"]
            },
            "restaurant": {"fontSize": F["sm"], "fontWeight": "700", "color": T["brand"]},
            "offerTitle": {
                "fontSize": F["lg"],
                "fontWeight": "800",
                "color": T["ink"],
                "lineHeight": 24
            },
            "price": {"fontSize": F["xl"], "fontWeight": "800", "color": T["ink"]},
            "priceBig": {"fontSize": 40, "fontWeight": "800", "color": T["ink"]},
            "strike": {
                "fontSize": F["md"],
                "color": T["muted"],
                "textDecorationLine": "line-through"
            },
            "save": {"fontSize": F["sm"], "fontWeight": "800", "color": T["good"]},
            "chip": {
                "paddingVertical": 6,
                "paddingHorizontal": S["md"],
                "borderRadius": R["pill"],
                "borderWidth": 1,
                "borderColor": T["border"],
                "backgroundColor": T["surface"]
            },
            "chipOn": {"backgroundColor": T["ink"], "borderColor": T["ink"]},
            "chipText": {"fontSize": F["sm"], "fontWeight": "600", "color": T["text"]},
            "chipTextOn": {"color": T["accentText"]},
            "tag": {
                "paddingVertical": 3,
                "paddingHorizontal": S["sm"],
                "borderRadius": R["pill"],
                "backgroundColor": T["sunken"]
            },
            "tagText": {"fontSize": F["xs"], "fontWeight": "700", "color": T["text"]},
            "badge": {
                "paddingVertical": 3,
                "paddingHorizontal": S["sm"],
                "borderRadius": R["pill"],
                "backgroundColor": T["goodSoft"]
            },
            "badgeText": {"fontSize": F["xs"], "fontWeight": "800", "color": T["good"]},
            "demo": {
                "paddingVertical": 2,
                "paddingHorizontal": S["sm"],
                "borderRadius": R["pill"],
                "borderWidth": 1,
                "borderColor": T["warn"]
            },
            "demoText": {"fontSize": 11, "fontWeight": "800", "color": T["warn"]},
            "note": {
                "backgroundColor": T["warnSoft"],
                "borderRadius": R["md"],
                "padding": S["md"],
                "gap": S["xs"]
            },
            "noteText": {"fontSize": F["sm"], "color": T["warn"], "lineHeight": 19},
            "input": {
                "paddingVertical": S["md"],
                "paddingHorizontal": S["md"],
                "borderRadius": R["md"],
                "borderWidth": 1,
                "borderColor": T["border"],
                "backgroundColor": T["surface"],
                "color": T["ink"],
                "fontSize": F["md"]
            },
            "inputMulti": {"minHeight": 72, "textAlignVertical": "top"},
            "field": {"gap": 6},
            "fieldRow": {"flexDirection": "row", "gap": S["md"]},
            "flex1": {"flex": 1},
            "btn": {
                "paddingVertical": 14,
                "paddingHorizontal": S["lg"],
                "borderRadius": R["md"],
                "backgroundColor": T["accent"],
                "alignItems": "center"
            },
            "btnText": {"color": T["accentText"], "fontWeight": "800", "fontSize": F["md"]},
            "btnGhost": {
                "paddingVertical": 10,
                "paddingHorizontal": S["md"],
                "borderRadius": R["md"],
                "borderWidth": 1,
                "borderColor": T["border"],
                "backgroundColor": T["surface"],
                "alignItems": "center"
            },
            "btnGhostText": {"color": T["ink"], "fontWeight": "700", "fontSize": F["sm"]},
            "btnDisabled": {"backgroundColor": T["border"]},
            "link": {"color": T["accent"], "fontWeight": "700", "fontSize": F["md"]},
            "msgGood": {
                "backgroundColor": T["goodSoft"],
                "borderRadius": R["md"],
                "padding": S["md"]
            },
            "msgGoodText": {"color": T["good"], "fontWeight": "700", "fontSize": F["md"]},
            "msgBad": {
                "backgroundColor": T["badSoft"],
                "borderRadius": R["md"],
                "padding": S["md"]
            },
            "msgBadText": {"color": T["bad"], "fontWeight": "700", "fontSize": F["md"]},
            "codeBox": {
                "backgroundColor": T["ink"],
                "borderRadius": R["lg"],
                "padding": S["xl"],
                "alignItems": "center",
                "gap": S["xs"]
            },
            "codeText": {
                "color": T["accentText"],
                "fontSize": 34,
                "fontWeight": "800",
                "letterSpacing": 6
            },
            "codeSub": {"color": "#d8d2c8", "fontSize": F["sm"]},
            "reason": {"flexDirection": "row", "gap": S["sm"], "alignItems": "flex-start"},
            "dot": {
                "width": 8,
                "height": 8,
                "borderRadius": 4,
                "marginTop": 7,
                "backgroundColor": T["accent"]
            },
            "empty": {
                "padding": S["xxl"],
                "alignItems": "center",
                "gap": S["sm"],
                "backgroundColor": T["surface"],
                "borderRadius": R["lg"],
                "borderWidth": 1,
                "borderColor": T["border"]
            },
            "tabbar": {
                "position": "absolute",
                "left": 0,
                "right": 0,
                "bottom": 0,
                "flexDirection": "row",
                "backgroundColor": T["surface"],
                "borderTopWidth": 1,
                "borderTopColor": T["border"],
                "paddingVertical": S["sm"],
                "paddingHorizontal": S["sm"]
            },
            "tab": {
                "flex": 1,
                "alignItems": "center",
                "paddingVertical": S["sm"],
                "borderRadius": R["md"],
                "gap": 2
            },
            "tabOn": {"backgroundColor": T["accentSoft"]},
            "tabText": {"fontSize": F["sm"], "fontWeight": "700", "color": T["muted"]},
            "tabTextOn": {"color": T["accent"]},
            "tabSub": {"fontSize": 11, "color": T["muted"]},
            "status": {
                "paddingVertical": 3,
                "paddingHorizontal": S["sm"],
                "borderRadius": R["pill"]
            },
            "statusText": {"fontSize": F["xs"], "fontWeight": "800"},
            "divider": {"height": 1, "backgroundColor": T["border"]}
        }
    );
}


"""Background / text colors for an offer or claim status pill."""
def:pub statusColors(state: str) -> list[str] {
    if state in ["active", "claimed"] {
        return [C["goodSoft"], C["good"]];
    }
    if state in ["scheduled", "paused"] {
        return [C["warnSoft"], C["warn"]];
    }
    if state == "redeemed" {
        return ["#e7f0fb", C["brand"]];
    }
    return [C["badSoft"], C["bad"]];
}


def:pub money(v: float) -> str {
    cents: int = int(round(v * 100));
    whole = cents // 100;
    rest = cents % 100;
    pad = "0" if rest < 10 else "";
    return "$" + str(whole) + "." + pad + str(rest);
}
