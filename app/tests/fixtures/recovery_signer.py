"""Test-only signing adapter for the T025 recovery browser case: it plays the holder of the
recovery trust set, which in a deployment is outside the product (the instance operator's
recovery adapter). Keys are generated in-test and live only in the test's temporary
directory; nothing here is product code or a real key.

    keygen --state-dir D --configuration C   writes D/trust.json (public) and D/signer.json
    sign   --state-dir D --configuration C --request R --new-verifier V --receipt OUT
"""
import argparse
import json
import sys
from base64 import urlsafe_b64decode
from pathlib import Path

from nacl.signing import SigningKey

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from app.operations.setup import OriginProfile
from app.tests.recovery_fixture import Signer, b64, receipt_for, trust_v2


def _signer(state):
    saved = json.loads((state / "signer.json").read_text(encoding="utf-8"))
    signer = Signer()
    signer.key = SigningKey(urlsafe_b64decode(saved["seed"] + "="))
    signer.key_id = saved["key_id"]
    return signer


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("keygen", "sign"))
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--configuration", required=True, type=Path)
    parser.add_argument("--request", type=Path)
    parser.add_argument("--new-verifier")
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    configuration = json.loads(args.configuration.read_text(encoding="utf-8"))
    profile = OriginProfile.from_dict(configuration["origin_profile"])
    if args.command == "keygen":
        signer = Signer()
        (args.state_dir / "signer.json").write_text(json.dumps(
            {"seed": b64(bytes(signer.key)), "key_id": signer.key_id}), encoding="utf-8")
        (args.state_dir / "trust.json").write_bytes(trust_v2(profile, signer))
        return
    signer = _signer(args.state_dir)
    trust = (args.state_dir / "trust.json").read_bytes()
    args.receipt.write_bytes(receipt_for(profile, args.request.read_bytes(), signer, trust,
                                         new_verifier=args.new_verifier))


if __name__ == "__main__":
    main()
