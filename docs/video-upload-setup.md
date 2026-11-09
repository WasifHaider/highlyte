# Video upload: one-time R2 setup

Uploaded videos go from the browser straight to the R2 bucket (the one in
`R2_BUCKET`), in 64 MB parts, using presigned URLs from the backend. This is
because Cloudflare Tunnel rejects request bodies over 100 MB. For that to
work, the bucket needs two settings, made once in the Cloudflare dashboard.

The upload button only appears when the backend has R2 configured
(`/api/health` reports `"uploads": true`).

## 1. CORS rule

Cloudflare dashboard → **R2** → your bucket → **Settings** → **CORS policy**
→ **Add CORS policy**, and paste this. Replace the first origin with the
address the team opens the app at.

```json
[
  {
    "AllowedOrigins": ["https://YOUR-APP-DOMAIN", "http://localhost:6100"],
    "AllowedMethods": ["PUT"],
    "AllowedHeaders": ["*"],
    "ExposeHeaders": ["ETag"],
    "MaxAgeSeconds": 3600
  }
]
```

`http://localhost:6100` is for teammates who run the app locally with
`start.bat`. `ExposeHeaders: ETag` is required: the browser reads each part's
ETag to finish the upload. Without it every upload fails with "Upload failed".

## 2. Lifecycle rule for abandoned uploads

If someone closes the tab mid-upload, the parts already sent stay in R2 as an
unfinished multipart upload. This rule deletes them.

Bucket → **Settings** → **Object lifecycle rules** → **Add rule**:

- Name: `abort-abandoned-uploads`
- Prefix: `uploads/`
- Action: **Abort incomplete multipart uploads** after **1 day**

Do not add a "delete objects" action on `uploads/`: finished originals must
stay until their project is deleted, or Swap and Regenerate stop working for
uploaded videos.

## How uploads are stored

- Original: `uploads/{id}/source.<ext>`. Poster: `uploads/{id}/thumb.jpg`.
- The job's source is `upload:{id}` instead of a YouTube link.
- Deleting the project deletes both files. Retrying a failed upload reuses
  the original.
- The server keeps a working copy in `data/cache`. If the cache sweeper
  removes it, it is downloaded from R2 again when needed.
- R2 storage costs about $0.015 per GB per month, and R2 has no download fees.
