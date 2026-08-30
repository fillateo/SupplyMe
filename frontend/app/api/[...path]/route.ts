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

async function proxy(request: Request, path: string[]): Promise<Response> {
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

export const dynamic = "force-dynamic";
