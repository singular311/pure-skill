export async function onRequestGet(context) {
  const key = context.params.key;
  if (!key || key.includes("..") || key.startsWith("/")) {
    return new Response("Not found", { status: 404 });
  }

  const object = await context.env.MANHWA_IMAGES.get(key);
  if (!object) return new Response("Not found", { status: 404 });

  const headers = new Headers();
  object.writeHttpMetadata(headers);
  headers.set("etag", object.httpEtag);
  headers.set("cache-control", "public, max-age=31536000, immutable");
  return new Response(object.body, { headers });
}
