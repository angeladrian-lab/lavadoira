"""Utilidades de red local: IP propia y búsqueda de dispositivos con el puerto 80 abierto (los Tapo lo usan)."""
import asyncio
import ipaddress
import re
import socket
import subprocess


def local_ip():
    """IP del Mac en la red local (no envía nada: connect en UDP solo elige la interfaz de salida)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def local_network(ip=None):
    """Red a la que pertenece la IP local. Limita el barrido a /22 (1.024 direcciones) como máximo."""
    ip = ip or local_ip()
    prefix = 24
    try:
        out = subprocess.run(["ifconfig"], capture_output=True, text=True, timeout=5).stdout
        m = re.search(rf"inet {re.escape(ip)} netmask (0x[0-9a-f]+)", out)
        if m:
            prefix = bin(int(m.group(1), 16)).count("1")
    except (OSError, subprocess.SubprocessError):
        pass
    return ipaddress.ip_network(f"{ip}/{max(prefix, 22)}", strict=False)


async def _open(ip, port, timeout):
    try:
        _, w = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout)
        w.close()
        return ip
    except (OSError, asyncio.TimeoutError):
        return None


async def scan(port=80, timeout=1.5, concurrency=128):
    """Devuelve las IP de la red local con ese puerto abierto (excepto la propia)."""
    me = local_ip()
    sem = asyncio.Semaphore(concurrency)

    async def one(ip):
        async with sem:
            return await _open(ip, port, timeout)

    hosts = [str(h) for h in local_network(me).hosts() if str(h) != me]
    return sorted(filter(None, await asyncio.gather(*(one(h) for h in hosts))), key=ipaddress.ip_address)
