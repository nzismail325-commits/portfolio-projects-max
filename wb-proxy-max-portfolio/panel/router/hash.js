/*
 * panel/router/hash.js —— 极简 hash 路由（本地自研，替代 vue-router）
 *
 * 只需四个能力：声明式路由表、hash 跳转、导航守卫（登录校验）、当前路由反应式。
 * 不引入外部依赖，也没有打包器——面板只面向两三个人的内网使用。
 */
import { reactive, computed } from "/vendor/vue.mjs";

function currentPath() {
  const raw = location.hash.replace(/^#/, "") || "/";
  return raw.startsWith("/") ? raw : "/" + raw;
}

const routeState = reactive({
  path: currentPath(),
  query: {},
  name: "",
  meta: {},
  params: {},
});

function parse(path) {
  const [pure, search] = path.split("?");
  const query = {};
  if (search) {
    for (const pair of search.split("&")) {
      if (!pair) continue;
      const [key, value = ""] = pair.split("=");
      query[decodeURIComponent(key)] = decodeURIComponent(value);
    }
  }
  return { path: pure || "/", query };
}

function match(routes, path) {
  for (const route of routes) {
    if (route.redirect) {
      if (route.path === "*" || route.path === path) {
        return { route: null, redirect: route.redirect };
      }
      continue;
    }
    if (!route.path.includes(":")) {
      if (route.path === path) {
        return { route, params: {} };
      }
      continue;
    }
    // 简单动态段：/x/:id
    const pattern = new RegExp("^" + route.path.replace(/:[^/]+/g, "([^/]+)") + "$");
    const hit = path.match(pattern);
    if (hit) {
      const keys = [...route.path.matchAll(/:([^/]+)/g)].map((m) => m[1]);
      const params = {};
      keys.forEach((key, index) => { params[key] = hit[index + 1]; });
      return { route, params };
    }
  }
  return { route: null };
}

export function createRouter(options) {
  const routes = options.routes || [];
  const guards = [];

  const router = {
    state: routeState,
    currentRoute: computed(() => routeState),
    beforeEach(fn) { guards.push(fn); return router; },
    getRoutes() { return routes; },
    push(target) {
      const path = typeof target === "string"
        ? target
        : location.hash; // 命名跳转由调用方给路径，此处不展开
      if (typeof target === "string") location.hash = path.startsWith("/") ? path : "/" + path;
    },
    /* B8：首次导航不再在 createRouter 内自动执行——此前模块初始化即导航，
       守卫（beforeEach）尚未注册，未登录访问业务页会直接渲染残留页面。
       现由 router/index.js 在注册完守卫后显式调用 start()。 */
    start: apply,
    replace(target) {
      if (typeof target === "string") {
        const path = target.startsWith("/") ? target : "/" + target;
        history.replaceState(null, "", "#" + path);
        apply();
      }
    },
    async go(target) {
      // 支持 { name, query } 与字符串
      if (typeof target === "string") {
        router.push(target);
        return;
      }
      const found = routes.find((route) => route.name === target.name);
      if (!found) return;
      const query = target.query
        ? "?" + Object.entries(target.query)
            .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`).join("&")
        : "";
      router.push(found.path + query);
    },
  };

  async function apply() {
    let { path, query } = parse(currentPath());
    let { route, params, redirect } = match(routes, path);
    if (redirect) {
      router.push(redirect);
      return;
    }
    if (!route) {
      router.push("/accounts");
      return;
    }
    for (const guard of guards) {
      const verdict = await guard({ ...route, path, query, params, fullPath: path });
      if (verdict && typeof verdict === "object" && verdict.name) {
        await router.go(verdict);
        return;
      }
      if (verdict === false) return;
    }
    routeState.path = path;
    routeState.query = query;
    routeState.name = route.name || "";
    routeState.meta = route.meta || {};
    routeState.params = params || {};
    if (route.meta?.title) document.title = `${route.meta.title} · Gateway 反代`;
  }

  window.addEventListener("hashchange", apply);
  return router;
}

export function createWebHashHistory() {
  return { mode: "hash" };
}

export function useRouter() {
  return {
    push: (path) => { location.hash = path.startsWith("/") ? path : "/" + path; },
    replace: (path) => {
      history.replaceState(null, "", "#" + (path.startsWith("/") ? path : "/" + path));
    },
  };
}

export function useRoute() {
  return routeState;
}

export default { createRouter, createWebHashHistory, useRouter, useRoute };
