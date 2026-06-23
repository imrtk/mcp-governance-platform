# Session Context

## Ortamlar
- **Ben (dev)**: DigitalOcean ✅ | vCenter ❌ | PostgreSQL ❌ | sadece DO test edebilirim
- **Kullanıcı (remote)**: DigitalOcean ❌ | vCenter ✅ | PostgreSQL ✅ (192.168.100.9) | tüm testleri burada yapar

## Son Commit'ler
- `b9081d6` — Dashboard: MCP Tool Test tabi (server/tool sec, calistir)
- `f8e7c42` — start.sh cleanup + wait fix
- `90bcb14` — cleanup'e pgsql-mcp eklendi (port 8020)
- `7a496bf` — gateway agent'lardan once baslatilsin

## Açık Sorunlar
- **Monitor agent çalışmıyor** — kapalı VM'leri açmıyor (henüz çözülmedi)

## Yapılacaklar / Bilinen Eksikler
- vCenter MCP için Dockerfile gerekebilir
- pyproject.toml'da pyvmomi bağımlılığı kontrol edilecek
- Diğer agent'lar (do, sysadmin, devops, secops) ve MCP'ler (file, shell, debian, do) registry'den çıkarıldı, devre dışı
