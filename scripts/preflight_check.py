"""EDITH Preflight Check — verifies Ollama server + model health."""
import requests
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

URL = "http://127.0.0.1:11434"
REQUIRED_MODELS = {"llama3.2", "llama3", "mistral"}
PRIMARY_MODEL = "llama3.2"


def check_server():
    try:
        r = requests.get(f"{URL}/api/tags", timeout=3)
        models = [m["name"] for m in r.json().get("models", [])]
        print("[PASS] Ollama server: ONLINE")
        return models
    except Exception as e:
        print(f"[FAIL] Ollama server OFFLINE: {e}")
        print("       Fix: run  'ollama serve'  in a terminal")
        sys.exit(1)


def check_models(models):
    available = {n.split(":")[0] for n in models}
    print(f"\nInstalled models ({len(models)} total):")
    for m in sorted(models):
        print(f"  - {m}")
    print("\nRequired models for EDITH:")
    all_ok = True
    for m in sorted(REQUIRED_MODELS):
        ok = m in available
        status = "PASS" if ok else "MISSING"
        print(f"  [{status}]  {m}")
        if not ok:
            all_ok = False
            print(f"         Fix: ollama pull {m}")
    return all_ok


def check_inference():
    print(f"\nInference test on '{PRIMARY_MODEL}'...")
    t0 = time.time()
    try:
        r = requests.post(
            f"{URL}/api/chat",
            json={
                "model": PRIMARY_MODEL,
                "messages": [
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": "Say only the word: READY"},
                ],
                "stream": False,
                "options": {"num_predict": 20, "temperature": 0.5},
            },
            timeout=60,
        )
        elapsed = time.time() - t0
        resp = r.json().get("message", {}).get("content", "").strip()
        print(f"  Response : {repr(resp)}")
        print(f"  Latency  : {elapsed:.1f}s")
        if resp:
            print(f"[PASS] '{PRIMARY_MODEL}' is responding correctly (via /api/chat)")
            return True
        else:
            print(f"[WARN] '{PRIMARY_MODEL}' returned empty response")
            return False
    except Exception as e:
        elapsed = time.time() - t0
        print(f"[FAIL] Inference error after {elapsed:.1f}s: {e}")
        return False


if __name__ == "__main__":
    print("=" * 50)
    print("  EDITH Model Preflight Check")
    print("=" * 50)

    models = check_server()
    models_ok = check_models(models)
    inference_ok = check_inference()

    print("\n" + "=" * 50)
    if models_ok and inference_ok:
        print("  ALL CHECKS PASSED — EDITH is ready to launch")
    else:
        print("  SOME CHECKS FAILED — fix issues above then retry")
    print("=" * 50)
