# make_license.py
# Usage: python make_license.py --hwid <HWID or empty> --days 365 --out license.lic --priv private.pem
# Requires: cryptography
import argparse, json, base64
from datetime import datetime, timedelta
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

parser = argparse.ArgumentParser()
parser.add_argument('--hwid', default='', help='HWID to bind (empty for generic)')
parser.add_argument('--days', type=int, default=365, help='Validity days')
parser.add_argument('--out', default='license.lic', help='Output license file')
parser.add_argument('--priv', default='private.pem', help='Private key PEM file')
args = parser.parse_args()

data = {
    "hwid": args.hwid,
    "issued": datetime.utcnow().isoformat(),
    "expiry": (datetime.utcnow() + timedelta(days=args.days)).isoformat(),
    "features": ["full"]
}

raw = json.dumps(data, ensure_ascii=False).encode('utf-8')

with open(args.priv, 'rb') as f:
    priv = serialization.load_pem_private_key(f.read(), password=None)

sig = priv.sign(
    raw,
    padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
    hashes.SHA256()
)

payload = {
    "data": base64.b64encode(raw).decode(),
    "sig": base64.b64encode(sig).decode()
}

with open(args.out, 'w', encoding='utf-8') as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)

print(f"Created license file: {args.out}")
