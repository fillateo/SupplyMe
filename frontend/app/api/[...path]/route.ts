/**
 * Server-side proxy to the API.
 *
 * The browser never talks to the API directly: requests go to this origin and
 * are forwarded from the server, so no API origin, token or credential is ever
 * in client JavaScript and there is no CORS preflight in production.
 *
 * This is a route handler rather than a `rewrites()` entry in next.config,
 * which is what it used to be. Next resolves rewrites at *build* time and bakes
 * them into the routes manifest, so `API_BASE_URL` was read while the image was
 * being built — where it does not exist — and every deployed console proxied to
 * `localhost:8080` inside its own container and answered 503. Which API to talk
 * to is a property of the deployment, not of the image; reading it here keeps
 * one image usable in every environment.
 */

const API_BASE_URL = () =>
  (process.env.API_BASE_URL ?? "http://localhost:8080").replace(/\/$/, "");

function isSafeSegment(segment: string): boolean {
  return segment.length > 0 && segment !== "." && segment !== ".." && !segment.includes("/");
}

async function proxy(request: Request, path: string[]): Promise<Response> {
  if (!path.every(isSafeSegment)) {
    // A "." / ".." / empty segment could otherwise walk the joined URL back
    // out of the /api/ prefix on the backend host it's forwarded to.
    return Response.json({ detail: "invalid path" }, { status: 400 });
  }
  const search = new URL(request.url).search;
  const target = `${API_BASE_URL()}/api/${path.join("/")}${search}`;

  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: request.method,
      headers: { "Content-Type": "application/json" },
      body: request.method === "GET" ? undefined : await request.text(),
      cache: "no-store",
    });
  } catch (error) {
    // Say which hop failed. "Cannot reach the API" is a different problem from
    // "the API said no", and the console renders them differently.
    return Response.json(
      { detail: `console could not reach the API at ${API_BASE_URL()}`, cause: String(error) },
      { status: 502 },
    );
  }

  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "Content-Type": upstream.headers.get("Content-Type") ?? "application/json",
      "Cache-Control": "no-store",
    },
  });
}

type Params = { params: Promise<{ path: string[] }> };

export async function GET(request: Request, { params }: Params) {
  return proxy(request, (await params).path);
}

export async function POST(request: Request, { params }: Params) {
  return proxy(request, (await params).path);
}

// GET and POST only, because those are the two methods the console issues.
// `PUT /api/missions/{id}/weights` exists on the API and has no console control
// behind it; adding one means adding a PUT export here too, or Next answers 405
// on this hop while the API itself would have accepted the call.

export const dynamic = "force-dynamic";
