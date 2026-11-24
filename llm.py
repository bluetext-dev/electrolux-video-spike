"""gpt-6-astra through OpenRouter, routed only to zero-data-retention providers.

Every call is appended to runs/usage.jsonl with its tokens and cost, and the run stops
when the spend recorded there passes BUDGET_USD.
"""
import base64, json, os, ssl, time, urllib.request, urllib.error

MODEL = os.environ.get("VP_MODEL", "openai/gpt-6-astra")
BUDGET_USD = float(os.environ.get("VP_BUDGET_USD", "10"))
HERE = os.path.dirname(os.path.abspath(__file__))
USAGE = os.path.join(HERE, "runs", "usage.jsonl")
# The key comes from OPENROUTER_API_KEY, or else from the macOS keychain item KEYCHAIN_SERVICE.
KEYCHAIN_SERVICE = os.environ.get("VP_KEYCHAIN_SERVICE", "openrouter-personal")


def api_key():
    import subprocess
    if os.environ.get("OPENROUTER_API_KEY"):
        return os.environ["OPENROUTER_API_KEY"]
    r = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"], capture_output=True, text=True)
    if r.returncode or not r.stdout.strip():
        raise SystemExit(f"no keychain item '{KEYCHAIN_SERVICE}': add it with  security add-generic-password -a $USER -s {KEYCHAIN_SERVICE} -w")
    return r.stdout.strip()


# This Python has no CA bundle of its own; use the system one.
SSL = ssl.create_default_context(cafile="/etc/ssl/cert.pem")


def spent():
    if not os.path.exists(USAGE):
        return 0.0
    return sum(json.loads(l).get("cost", 0) for l in open(USAGE) if l.strip())


def image_part(path):
    data = base64.b64encode(open(path, "rb").read()).decode()
    mime = "image/png" if path.endswith(".png") else "image/jpeg"
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}}


def ask(stage, system, content, max_tokens=32000, effort="medium"):
    """content: a string or a list of message parts (text and images). Returns the text."""
    if spent() >= BUDGET_USD:
        raise SystemExit(f"budget reached: ${spent():.2f} of ${BUDGET_USD:.2f}")
    body = {
        "model": MODEL,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
        "max_tokens": max_tokens,
        "reasoning": {"effort": effort},
        "provider": {"zdr": True, "data_collection": "deny"},
        "usage": {"include": True},
    }
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + api_key(), "Content-Type": "application/json"},
    )
    t0 = time.time()
    for attempt in range(4):
        try:
            d = json.load(urllib.request.urlopen(req, timeout=900, context=SSL))
            break
        except urllib.error.HTTPError as e:
            if e.code in (429, 502, 503) and attempt < 3:
                time.sleep(10 * (attempt + 1))
                continue
            raise SystemExit(f"{stage}: HTTP {e.code} {e.read()[:500]!r}")
    if d.get("error"):
        raise SystemExit(f"{stage}: {d['error']}")
    u = d.get("usage", {})
    rec = {
        "stage": stage, "provider": d.get("provider"), "seconds": round(time.time() - t0, 1),
        "prompt_tokens": u.get("prompt_tokens"), "completion_tokens": u.get("completion_tokens"),
        "reasoning_tokens": (u.get("completion_tokens_details") or {}).get("reasoning_tokens"),
        "cost": u.get("cost", 0),
    }
    os.makedirs(os.path.dirname(USAGE), exist_ok=True)
    open(USAGE, "a").write(json.dumps(rec) + "\n")
    print(f"  {stage}: {rec['seconds']}s, {rec['prompt_tokens']} in / {rec['completion_tokens']} out, ${rec['cost']:.3f} (total ${spent():.2f})")
    return d["choices"][0]["message"]["content"]


def code_block(text, lang="python"):
    """The last fenced block in a reply, or the whole reply if it has none."""
    import re
    blocks = re.findall(r"```(?:" + lang + r")?\s*\n(.*?)```", text, flags=re.S)
    return blocks[-1] if blocks else text
