# API КорпМессенджера
Все ответы — JSON. Авторизация: заголовок `Authorization: Bearer <token>` (или `?token=` для файлов).

| Метод | Путь | Описание |
|---|---|---|
| POST | /api/register | {username, password, display_name} |
| POST | /api/login | {username, password} → {token, user} |
| POST | /api/logout | отозвать токен |
| GET | /api/me | текущий пользователь + unread_total |
| POST | /api/status | {status: online\|away\|offline} |
| GET | /api/dialogs | список чатов с бейджами непрочитанных |
| GET | /api/users | каталог сотрудников |
| GET/POST/DELETE | /api/contacts[/{id}] | контакты |
| GET | /api/messages?type=dm\|group&id=N | история (отмечает прочтение) |
| POST | /api/messages | {type, text, peer_id\|group_id, file_id?} |
| DELETE | /api/messages/{id} | автор или админ |
| POST | /api/upload | multipart `file` → {id,...} |
| GET | /api/files/{id}/raw?dl=1 | скачать (доступ по участникам чата) |
| POST/PATCH/DELETE | /api/groups[/…]/members/roles | создание/редактирование групп |
| GET | /api/admin/stats, users, groups, files, messages | только админ |

WebSocket (Socket.IO, `?token=`): события `new_message`, `message_deleted`, `presence`,
`contact_added`, `group_invite`, `group_removed`; клиент шлёт `set_away`/`set_online`/`ping_alive`.
