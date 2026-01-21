# Roadmap

## Planned

### Public S3 versioning API

Extract S3 point-in-time version querying into a public class (`S3Path`) mirroring `ParamPath`:

```python
from ssmbak.restore.s3 import S3Path

s3path = S3Path(key, checktime, region, bucketname)
s3path.preview()   # version that would be restored
s3path.restore()   # copy that version to current
```

This would:
- Move `_get_versions(use_tags=False)` logic into a clean public API
- Let external callers (e.g., xeo) do S3-to-S3 point-in-time restore
- Keep `ParamPath` for SSM-specific restore (S3-to-SSM with tags)

Currently xeo uses internal `Resource._get_versions()` directly as a workaround.
