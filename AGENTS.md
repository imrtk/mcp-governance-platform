# Session Context

## Ortamlar
- **Ben (dev)**: DigitalOcean ✅ | vCenter ❌ | PostgreSQL ❌ | sadece DO test edebilirim
- **Kullanıcı (remote)**: DigitalOcean ❌ | vCenter ✅ | PostgreSQL ✅ (192.168.100.9) | tüm testleri burada yapar

## Son Commit'ler
- `31ce660` — fix: Zabbix 7.4 API token auth (Authorization Bearer header)
- `1eced53` — monitor-agent: Zabbix alert/event takibi (check_zabbix)
- `4a4c8dc` — policy: zabbix_delete_host kalici olarak bloklandi
- `8a5738d` — zabbix-mcp + zabbix-agent: host CRUD, alert, metric, event, action tool'lari
- `8b0ab26` — guvenlik: pgsql_execute yerine ozel pgsql_insert_metric tool'u
- `bf2f12c` — fix: pgsql_execute tool'una policy izni eklendi
- `748228c` — monitor-agent: vCenter event/alarm + kaynak kullanimi monitoring
- `0157897` — fix: policy'e pgsql tool'lari eklendi

## Açık Sorunlar
- (şu an yok)
- Son: Zabbix 7.4 API auth düzeltildi — `auth` field body'den kaldırıldı, `Authorization: Bearer` header'a taşındı

## Yapılacaklar / Bilinen Eksikler
- vCenter MCP için Dockerfile gerekebilir
- pyproject.toml'da pyvmomi bağımlılığı kontrol edilecek
- Diğer agent'lar (do, sysadmin, devops, secops) ve MCP'ler (file, shell, debian, do) registry'den çıkarıldı, devre dışı
