# Session Context

## Ortamlar
- **Ben (dev)**: DigitalOcean ✅ | vCenter ❌ | PostgreSQL ❌ | sadece DO test edebilirim
- **Kullanıcı (remote)**: DigitalOcean ❌ | vCenter ✅ | PostgreSQL ✅ (192.168.100.9) | tüm testleri burada yapar

## Son Commit'ler
- `1eced53` — monitor-agent: Zabbix alert/event takibi (check_zabbix)
- `4a4c8dc` — policy: zabbix_delete_host kalici olarak bloklandi
- `8a5738d` — zabbix-mcp + zabbix-agent: host CRUD, alert, metric, event, action tool'lari
- `8b0ab26` — guvenlik: pgsql_execute yerine ozel pgsql_insert_metric tool'u
- `bf2f12c` — fix: pgsql_execute tool'una policy izni eklendi
- `748228c` — monitor-agent: vCenter event/alarm + kaynak kullanimi monitoring
- `0157897` — fix: policy'e pgsql tool'lari eklendi
- `a78573a` — docs: AGENTS.md guncellendi

## Açık Sorunlar
- (şu an yok)

## Yapılacaklar / Bilinen Eksikler
- vCenter MCP için Dockerfile gerekebilir
- pyproject.toml'da pyvmomi bağımlılığı kontrol edilecek
- Diğer agent'lar (do, sysadmin, devops, secops) ve MCP'ler (file, shell, debian, do) registry'den çıkarıldı, devre dışı
