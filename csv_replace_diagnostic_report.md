# CSV Replace Diagnostic Report

Generated at: `2026-11-07T13:02:19Z`

## Scope

- Pengujian dilakukan hanya pada file dummy di `reports/retraining/diagnostics/`.
- Tidak ada `os.replace` terhadap CSV produksi.
- Tidak ada training dijalankan.

## Production Snapshot

- CSV produksi: `D:\NEXORA_AI_v2\reports\retraining\batch_execution_log.csv`
- LastWriteTime (before): `2026-11-07T11:43:01.644176+00:00`
- LastWriteTime (after): `2026-11-07T11:43:01.644176+00:00`
- SHA-256 (before): `d73f196d5a313d1ab3fc878ea354b944aecaf8d074e94bc5dda42900e0bf2dd8`
- SHA-256 (after): `d73f196d5a313d1ab3fc878ea354b944aecaf8d074e94bc5dda42900e0bf2dd8`

## Test Results

| Test | Status | Details |
|---|---|---|
| `create_dummy_csv` | **PASS** | Created dummy_execution_log.csv |
| `tempfile_same_directory` | **PASS** | temp=tmp_replace_ywjrd5md.csv |
| `normal_write_dummy_csv` | **PASS** | Append row succeeded |
| `os_replace_normal` | **PASS** | os.replace succeeded |
| `os_replace_locked` | **PASS** | os.replace blocked as expected |
| `directory_rename_delete_permission` | **PASS** | Rename+delete in diagnostics dir succeeded |
| `production_csv_untouched` | **PASS** | Production CSV hash/mtime unchanged |
| `backup_files_untouched` | **PASS** | Backup files hash unchanged |

## Exception Diagnostics

- `os_replace_locked`: `{"type": "PermissionError", "message": "[WinError 5] Access is denied: 'D:\\\\NEXORA_AI_v2\\\\reports\\\\retraining\\\\diagnostics\\\\dummy_execution_log.new.csv' -> 'D:\\\\NEXORA_AI_v2\\\\reports\\\\retraining\\\\diagnostics\\\\dummy_execution_log.csv'", "errno": 13, "winerror": 5, "strerror": "Access is denied"}`

## Folder Access & ACL

- diagnostics writable: `True`
- reports/retraining writable: `True`

```text
FileSystemRights AccessControlType IdentityReference                                  IsInherited Inh
                                                                                                                    eri
                                                                                                                    tan
                                                                                                                    ceF
                                                                                                                    lag
                                                                                                                      s
                  ---------------- ----------------- -----------------                                  ----------- ---
               Modify, Synchronize             Allow LAPTOP-DJU8AEA7\CodexSandboxUsers                         True rit
               Modify, Synchronize             Allow S-1-5-21-2995464288-435325171-1173009678-206077610        True rit
                       FullControl             Allow LAPTOP-DJU8AEA7\CodexSandboxOffline                       True one
                       FullControl             Allow CREATOR OWNER                                             True rit
                       FullControl             Allow NT AUTHORITY\SYSTEM                                       True rit
                       FullControl             Allow BUILTIN\Administrators                                    True rit
Write, ReadAndExecute, Synchronize             Allow BUILTIN\Users                                             True rit
```

## Relevant Processes Snapshot

- Tidak ada proses relevan yang terdeteksi pada snapshot.

## Conclusion

Status keseluruhan: **PASS**
- Bukti menunjukkan replace pada file yang di-lock memang gagal (expected).
- CSV produksi dan file backup tetap tidak berubah selama diagnosis.
