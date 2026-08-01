export async function onRequestGet(context) {
  try {
    const key = context.params.key;

    if (!key || key.includes("..") || key.startsWith("/")) {
      return new Response("Bad key: " + key, { status: 400 });
    }

    const object = await context.env.MANHWA_IMAGES.get(key);

    if (!object) {
      return new Response("Not found: " + key, { status: 404 });
    }

    const headers = new Headers();
    object.writeHttpMetadata(headers);
    headers.set("cache-control", "public, max-age=31536000, immutable");

    return new Response(object.body, { headers });
  } catch (e) {
    return new Response(
      `${e.name}\n${e.message}\n${e.stack}`,
      { status: 500 }
    );
  }
}