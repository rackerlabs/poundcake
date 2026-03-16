import type { ZodType } from "zod";

export class ApiError extends Error {
  status: number;
  body: unknown;

  constructor(message: string, status: number, body: unknown) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

function buildNextUrl(): string {
  return `${window.location.pathname}${window.location.search}`;
}

function redirectToLogin(): void {
  const target = new URL("/login", window.location.origin);
  target.searchParams.set("next", buildNextUrl());
  window.location.assign(target.toString());
}

export async function apiFetch<T>(
  path: string,
  schema: ZodType<T>,
  init: RequestInit = {},
  options: { allowUnauthorized?: boolean } = {},
): Promise<T> {
  const response = await fetch(path, {
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      ...(init.headers || {}),
    },
    ...init,
  });

  if (response.status === 401 && !options.allowUnauthorized) {
    redirectToLogin();
    throw new ApiError("Authentication required", 401, null);
  }

  const contentType = response.headers.get("content-type") || "";
  const body = contentType.includes("application/json")
    ? await response.json().catch(() => null)
    : await response.text().catch(() => "");

  if (!response.ok) {
    const detail =
      typeof body === "object" && body && "detail" in body
        ? String((body as { detail: unknown }).detail)
        : response.statusText;
    throw new ApiError(detail || `Request failed (${response.status})`, response.status, body);
  }

  return schema.parse(body);
}

export function apiGet<T>(path: string, schema: ZodType<T>): Promise<T> {
  return apiFetch<T>(path, schema);
}

export function apiPost<T>(path: string, schema: ZodType<T>, body?: unknown): Promise<T> {
  return apiFetch<T>(path, schema, {
    method: "POST",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

export function apiPut<T>(path: string, schema: ZodType<T>, body: unknown): Promise<T> {
  return apiFetch<T>(path, schema, {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

export function apiPatch<T>(path: string, schema: ZodType<T>, body: unknown): Promise<T> {
  return apiFetch<T>(path, schema, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export function apiDelete<T>(path: string, schema: ZodType<T>): Promise<T> {
  return apiFetch<T>(path, schema, { method: "DELETE" });
}
