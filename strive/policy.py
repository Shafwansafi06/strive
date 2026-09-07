"""Business context is separate from the three acoustic STRIVE tracks."""

def context_risk(context):
    amount = context.get("amount_inr", 0)
    score = .35 if amount >= 1_000_000 else .15 if amount >= 100_000 else 0
    score += .2 * bool(context.get("urgent"))
    score += .25 * bool(context.get("new_beneficiary"))
    score += .2 * bool(context.get("privileged_request"))
    return min(1., score)


def decide(auth, context, warning=.5, alert=.75):
    ctx = context_risk(context)
    decision = None if auth is None else 1 - (1 - auth) * (1 - .5 * ctx)
    if auth is None:
        action = "HOLD_AND_VERIFY" if ctx >= .5 else "AWAIT_EVIDENCE"
        level = "analyzing"
    elif decision >= alert:
        level, action = "alert", "HOLD_AND_VERIFY"
    elif decision >= warning or ctx >= .7:
        level, action = "warning", "VERIFY_CALLER"
    else:
        level, action = "low", "CONTINUE_MONITORING"
    return {"context_risk": ctx, "decision_risk": decision, "alert_level": level,
            "recommended_action": action}
