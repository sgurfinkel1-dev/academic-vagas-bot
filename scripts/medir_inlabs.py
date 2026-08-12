"""Mede o custo real de UM dia do INLABS: login, download dos 3 ZIPs, tamanho e tempo.
Uso:  set INLABS_EMAIL / INLABS_SENHA no ambiente e rodar:  python medir_inlabs.py [AAAA-MM-DD]
Nao grava nada em disco alem do proprio zip em pasta temporaria.
"""
import os, sys, time, zipfile, io, tempfile, re
import httpx

EMAIL = os.getenv("INLABS_EMAIL") or os.getenv("INLABS_USER") or ""
SENHA = os.getenv("INLABS_SENHA") or os.getenv("INLABS_PASS") or ""
if not (EMAIL and SENHA):
    sys.exit("defina INLABS_EMAIL e INLABS_SENHA no ambiente antes de rodar")

DIA = sys.argv[1] if len(sys.argv) > 1 else time.strftime("%Y-%m-%d")
BASE = "https://inlabs.in.gov.br"
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"}

t0 = time.time()
with httpx.Client(headers=H, timeout=120, follow_redirects=True) as c:
    r = c.post(f"{BASE}/logar.php", data={"email": EMAIL, "password": SENHA})
    cookie = c.cookies.get("inlabs_session_cookie")
    print(f"login: {r.status_code} em {time.time()-t0:.1f}s | cookie={'ok' if cookie else 'AUSENTE'}")
    if not cookie:
        sys.exit("login falhou (sem cookie de sessao) — confira email/senha")

    total_bytes = total_itens = 0
    for secao in ("DO1", "DO2", "DO3"):
        nome = f"{DIA}-{secao}.zip"
        t = time.time()
        rr = c.get(f"{BASE}/index.php?p={DIA}&dl={nome}")
        dt = time.time() - t
        if rr.status_code != 200 or not rr.content[:2] == b"PK":
            print(f"  {secao}: sem arquivo ({rr.status_code}, {len(rr.content)}b em {dt:.1f}s)")
            continue
        z = zipfile.ZipFile(io.BytesIO(rr.content))
        xmls = z.namelist()
        cru = sum(i.file_size for i in z.infolist())
        # quantos artigos citam concurso/professor — a fatia que interessa ao bot
        rel = 0
        pat = re.compile(rb"professor|docente|concurso p|magist", re.I)
        for n in xmls:
            if pat.search(z.read(n)):
                rel += 1
        total_bytes += len(rr.content); total_itens += len(xmls)
        print(f"  {secao}: {len(rr.content)/1e6:.1f} MB zip / {cru/1e6:.1f} MB xml | "
              f"{len(xmls)} artigos, {rel} citam professor/docente/concurso | {dt:.1f}s")

print(f"\nTOTAL dia {DIA}: {total_bytes/1e6:.1f} MB, {total_itens} artigos, "
      f"{time.time()-t0:.1f}s de ponta a ponta")
print(f"projecao 30 dias: {total_bytes*30/1e6:.0f} MB, ~{total_itens*30} artigos, "
      f"~{(time.time()-t0)*30/60:.1f} min")
