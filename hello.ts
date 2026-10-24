import { createHash, timingSafeEqual } from "node:crypto";
import { Pool } from "pg";
import { S3Client, GetObjectCommand } from "@aws-sdk/client-s3";

const secret = process.env.ORIGIN_SECRET;
if (!secret) throw new Error("ORIGIN_SECRET is required");
const expected = Buffer.from(secret);
const pool = new Pool({ connectionString: process.env.DATABASE_URL, max: 2, idleTimeoutMillis: 10000 });
const storage = new S3Client({ endpoint: process.env.AWS_ENDPOINT_URL_S3, region: process.env.AWS_REGION, forcePathStyle: true });

export default {
  async fetch(request: Request): Promise<Response> {
    const provided = Buffer.from(request.headers.get("x-secret") ?? "");
    if (provided.length !== expected.length || !timingSafeEqual(provided, expected)) return new Response("Unauthorized", { status: 401 });
    if (request.method !== "POST") return new Response("Method not allowed", { status: 405 });
    try {
      const text = await request.text();
      if (text.length > 2000) return new Response("Request too large", { status: 413 });
      const body = JSON.parse(text);
      if (![body.document, body.version, body.org, body.user].every(x => typeof x === "string" && /^[a-f0-9-]{36}$/.test(x))) return new Response("Invalid request", { status: 400 });
      const { rows } = await pool.query(
        "SELECT v.checksum,v.original,v.original_key,v.original_size,v.number FROM document_versions v JOIN documents d ON d.id=v.document WHERE d.id=$1 AND v.id=$2 AND d.org=$3 AND (d.visibility='workspace' OR d.owner=$4)",
        [body.document, body.version, body.org, body.user],
      );
      const row = rows[0];
      if (!row) return new Response("Not found", { status: 404 });
      let original: Uint8Array | null = row.original;
      if (row.original_key) {
        const result = await storage.send(new GetObjectCommand({ Bucket: process.env.NEON_STORAGE_BUCKET ?? "assets", Key: row.original_key }));
        if (Number(result.ContentLength) > 10 * 1024 * 1024) throw new Error("Oversized original");
        original = result.Body ? await result.Body.transformToByteArray() : null;
      }
      if (!original) return Response.json({ verified: false, reason: "Original unavailable" });
      const checksum = createHash("sha256").update(original).digest("hex");
      return Response.json({ verified: checksum === row.checksum, checksum, version: row.number, bytes: original.byteLength, storage: row.original_key ? "neon" : "database" });
    } catch {
      return Response.json({ error: "Source verification is temporarily unavailable" }, { status: 503 });
    }
  },
};
