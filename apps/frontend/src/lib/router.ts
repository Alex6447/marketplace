import { useEffect, useState } from "react";

// Крошечный hash-роутер без зависимостей: #/ → проекты,
// #/projects/:id → проект, #/products/:id → товар. Поддерживает back/refresh.

export type Route =
  | { name: "projects" }
  | { name: "project"; id: string }
  | { name: "product"; id: string };

function parse(hash: string): Route {
  const path = hash.replace(/^#/, "");
  const project = path.match(/^\/projects\/([^/]+)$/);
  if (project) return { name: "project", id: decodeURIComponent(project[1]) };
  const product = path.match(/^\/products\/([^/]+)$/);
  if (product) return { name: "product", id: decodeURIComponent(product[1]) };
  return { name: "projects" };
}

export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parse(window.location.hash));
  useEffect(() => {
    const onChange = () => setRoute(parse(window.location.hash));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}

export function navigate(to: Route): void {
  const hash =
    to.name === "projects"
      ? "#/"
      : to.name === "project"
        ? `#/projects/${to.id}`
        : `#/products/${to.id}`;
  if (window.location.hash !== hash) window.location.hash = hash;
}

/** Ссылочный href для тех же маршрутов (для <a>, чтобы работал Ctrl+click). */
export function href(to: Route): string {
  return to.name === "projects"
    ? "#/"
    : to.name === "project"
      ? `#/projects/${to.id}`
      : `#/products/${to.id}`;
}
