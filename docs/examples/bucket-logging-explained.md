# How Bucket Logging Works — Full Picture from the Knowledge Graph

Bucket logging in the Scality S3 platform is a **4-service pipeline** spanning 4 repos + Federation config:

## Step 1: Admin enables the feature (cloudserver config)

An admin must enable server access logging at the system level. It's **off by default**.

`parseServerAccessLogs()` in `lib/Config.js` (cloudserver):
```javascript
mode: serverAccessLogsModes.DISABLED,  // default
outputFile: '/logs/server-access.log',
highWaterMarkBytes: 10485760,          // 10MB buffer
retryReopenDelayMS: 1000,
checkFileRotationIntervalMS: 10000,
```

Federation deploys this via `roles/run-s3/templates/config.json.j2`:
```json
"serverAccessLogs": {
    "mode": "{{ server_access_logs_mode }}",
    "outputFile": "{{ server_access_logs_output_file }}"
}
```

If `mode !== 'ENABLED'`, the APIs return `NotImplemented`.

## Step 2: User configures per-bucket logging (cloudserver S3 API)

```
PUT /{source-bucket}?logging
```

`bucketPutLogging()` in `lib/api/bucketPutLogging.js` (cloudserver):
- Parses XML: `<TargetBucket>` + `<TargetPrefix>` (e.g., `logs/`)
- Uses Arsenal's `BucketLoggingStatus.fromXML()` to validate
- Stores config in bucket metadata (via MetaData/bucketd)

## Step 3: CloudServer emits access logs (every S3 request)

`serverAccessLogger.js` in `lib/utilities/` (cloudserver) hooks into every request:
- `logServerAccess(req, res)` -- main request logging
- `logBatchDeleteObject()` -- multi-delete operations
- `logCopySourceAccess()` -- source side of copy operations
- `storeServerAccessLogInfo()` (`metadataUtils.js`) -- attaches logging metadata to the request early on, including whether the bucket has logging enabled

All logs are written as **JSON to a file** (`/logs/server-access.log`), NOT directly to S3.

## Step 4: FluentBit ships logs to ClickHouse (analytics pipeline)

Federation's `roles/run-s3-analytics-fluentbit/templates/fluent-bit.conf.j2`:
- Tails the log file (with position tracking in SQLite)
- Parses JSON, filters via allowlist
- Batches and flushes every 10 seconds
- Routes through OpenResty proxy to ClickHouse

## Step 5: ClickHouse stores everything (with logging metadata)

Federation's `roles/run-s3-analytics-clickhouse/templates/2.access_logs.sql.j2`:
```sql
CREATE TABLE IF NOT EXISTS logs.access_logs (
    startTime       DateTime64(3),
    requester       Nullable(String),
    operation       Nullable(String),
    bucketName      ...,
    objectKey       ...,
    -- These fields are key for log delivery:
    loggingEnabled        ...,
    loggingTargetBucket   ...,
    loggingTargetPrefix   ...,
)
```

The `loggingEnabled`, `loggingTargetBucket`, `loggingTargetPrefix` columns mark which log entries need to be delivered as S3 objects.

## Step 6: log-courier reads from ClickHouse and delivers to S3 (Go)

`LogRecord` struct in `pkg/logcourier/logrecord.go` (log-courier):
```go
type LogRecord struct {
    BucketOwner    *string   `ch:"bucketOwner"`
    BucketName     string    `ch:"bucketName"`
    StartTime      time.Time `ch:"startTime"`
    ClientIP       *string   `ch:"clientIP"`
    Requester      *string   `ch:"requester"`
    ReqID          string    // ... all AWS access log fields
}
```

log-courier:
- Connects to ClickHouse via **native TCP** (from Federation config: `log-courier.yml.j2`)
- Has **S3 credentials** (from Federation config: `env.j2` with `S3_ACCESS_KEY_ID`)
- Queries ClickHouse for logs where `loggingEnabled = true`
- Groups by `loggingTargetBucket` / `loggingTargetPrefix`
- Formats entries in **AWS access log format** (following the field order in `LogRecord`)
- PUTs log objects into the target S3 bucket via the S3 API

## Architecture

```
User: PUT /my-bucket?logging -> targetBucket=logs-bucket, targetPrefix=logs/
                    |
                    v
         +--- cloudserver ---+
         | stores config in  |
         | bucket metadata   |
         |                   |
         | on every request: |
         | serverAccessLogger|---- JSON --> /logs/server-access.log
         +-------------------+                      |
                                                    v
                                              +-- FluentBit --+
                                              | tail + parse   |
                                              | filter + batch |
                                              +-------+--------+
                                                      v
                                              +-- OpenResty --+
                                              | proxy/route    |
                                              +-------+--------+
                                                      v
                                            +--- ClickHouse ---+
                                            | logs.access_logs  |
                                            | (loggingEnabled,  |
                                            |  loggingTarget    |
                                            |  Bucket/Prefix)   |
                                            +--------+----------+
                                                     v
                                            +-- log-courier (Go) --+
                                            | reads ClickHouse      |
                                            | formats AWS log       |
                                            | PUTs to target bucket |
                                            +-----------+-----------+
                                                        v
                                            +-- logs-bucket/logs/ --+
                                            | access log S3 objects  |
                                            | (AWS format)           |
                                            +------------------------+
```

## Repos involved

| Step | Repo | Language |
|------|------|----------|
| S3 API + log generation | cloudserver | JavaScript |
| Bucket metadata model | Arsenal | TypeScript |
| Log shipping config | Federation | Jinja2/YAML |
| ClickHouse schema | Federation | SQL |
| Log delivery to S3 | log-courier | Go |

Five repos, three languages, plus Federation config -- all queryable from a single knowledge graph.
