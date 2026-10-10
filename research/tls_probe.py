"""TLS 探针 v2：不校验证书，直接打印 Cloudflare 边缘证书内容，识别是否存在中间人"""

import socket
import ssl
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TARGETS = [
    ("region1.v2.argotunnel.com", 7844, None),
    ("region1.v2.argotunnel.com", 7844, "http://127.0.0.1:10808"),
    ("dock.frog755.cc.cd", 443, None),
    ("one.one.one.one", 443, None),
    ("www.baidu.com", 443, None),
]


def tcp(host: str, port: int, proxy: str | None):
    if proxy:
        phost, pport = proxy.replace("http://", "").split(":")
        sock = socket.create_connection((phost, int(pport)), timeout=12)
        sock.sendall(f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n\r\n".encode())
        head = sock.recv(4096).decode("latin-1", "replace").split("\r\n")[0]
        if "200" not in head:
            raise RuntimeError(f"代理 CONNECT 被拒: {head}")
        return sock
    return socket.create_connection((host, port), timeout=12)


def probe(host: str, port: int, proxy: str | None) -> None:
    label = f"{host}:{port}" + (" [走代理]" if proxy else " [直连]")
    try:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with ctx.wrap_socket(tcp(host, port, proxy), server_hostname=host) as ss:
            der = ss.getpeercert(binary_form=True)
            print(f"[{label}] ✅ TLS {ss.version()}")
        with tempfile.NamedTemporaryFile(suffix=".der", delete=False) as f:
            f.write(der)
            path = f.name
        info = subprocess.run(
            ["openssl", "x509", "-inform", "DER", "-in", path, "-noout",
             "-issuer", "-subject", "-dates"],
            capture_output=True, text=True,
        ).stdout.strip()
        print("    " + (info.replace("\n", "\n    ") if info else "(openssl 解析不可用)"))
        try:
            vctx = ssl.create_default_context()
            with vctx.wrap_socket(tcp(host, port, proxy), server_hostname=host):
                pass
            print("    信任校验: ✅ 通过（证书链受系统信任）")
        except Exception as e:
            print(f"    信任校验: ❌ 不通过 → {str(e)[:120]}")
    except Exception as e:
        print(f"[{label}] ❌ {type(e).__name__}: {str(e)[:130]}")


for h, p, px in TARGETS:
    probe(h, p, px)
    print()
