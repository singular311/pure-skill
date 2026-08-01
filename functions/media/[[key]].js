export async function onRequestGet(context) {
  const key = context.params.key;

  const object = await context.env.MANHWA_IMAGES.get(key);

  if (!object)
    return new Response("Not found", { status: 404 });

  const headers = new Headers();
  object.writeHttpMetadata(headers);

  return new Response(object.body, { headers });
}