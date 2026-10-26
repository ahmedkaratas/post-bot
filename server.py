#!/usr/bin/env python3
import http.server
import socketserver
import webbrowser
import socket
import os
import sys

PORT = 8080

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        # Sade log
        pass

if __name__ == '__main__':
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    local_ip = get_local_ip()

    print("\n" + "="*50)
    print("🚀 InstaFit 1080x1350 Başlatıldı!")
    print("="*50)
    print(f"🖥️  Mac üzerinden açmak için : http://localhost:{PORT}")
    print(f"📱 iPhone / Mobil için     : http://{local_ip}:{PORT}")
    print("="*50)
    print("Durdurmak için Ctrl + C tuşlarına basın.\n")

    # Tarayıcıyı otomatik aç
    webbrowser.open(f"http://localhost:{PORT}")

    with socketserver.TCPServer(("", PORT), QuietHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nSunucu kapatıldı.")
            sys.exit(0)
