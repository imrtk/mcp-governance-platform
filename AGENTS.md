# Session Context

## Ortamlar
- **Ben (dev)**: DigitalOcean ❌ | vCenter ❌ | PostgreSQL ❌ | hiçbir şey test edemem
- **Kullanıcı (remote)**: DigitalOcean ❌ | vCenter ✅ | PostgreSQL ✅ (192.168.100.9) | tüm testleri burada yapar

## Son Commit'ler
- `bc3d189` — fix: alert sayisi degil icerik kontrolu - aktif problem varsa her 5dk analiz
- `31ce660` — fix: Zabbix 7.4 API token auth (Authorization Bearer header)
- `1eced53` — monitor-agent: Zabbix alert/event takibi (check_zabbix)
- `4a4c8dc` — policy: zabbix_delete_host kalici olarak bloklandi
- `8a5738d` — zabbix-mcp + zabbix-agent: host CRUD, alert, metric, event, action tool'lari
- `8b0ab26` — guvenlik: pgsql_execute yerine ozel pgsql_insert_metric tool'u
- `748228c` — monitor-agent: vCenter event/alarm + kaynak kullanimi monitoring

## Açık Sorunlar
- (şu an yok)

## Yapılacaklar / Bilinen Eksikler
- vCenter MCP için Dockerfile gerekebilir
- pyproject.toml'da pyvmomi bağımlılığı kontrol edilecek
- DigitalOcean (do-mcp, do-agent) tamamen kaldırıldı
- sysadmin, devops, secops agent'ları ve file, shell, debian MCP'leri tamamen kaldırıldı
