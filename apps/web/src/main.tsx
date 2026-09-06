import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { Suspense, lazy } from "react";
import ReactDOM from "react-dom/client";
import { RouterProvider, createBrowserRouter } from "react-router-dom";
import App from "./App";
import { ThemeProvider } from "./theme/ThemeContext";
import "./index.css";

// One lazy import per screen — the bundle is code-split per route.
const Overview = lazy(() => import("./screens/Overview"));
const RouteExplorer = lazy(() => import("./screens/RouteExplorer"));
const SectorHeatmap = lazy(() => import("./screens/SectorHeatmap"));
const LeadTime = lazy(() => import("./screens/LeadTime"));
const MethodConsole = lazy(() => import("./screens/MethodConsole"));
const Audit = lazy(() => import("./screens/Audit"));

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 60_000, retry: 1 } },
});

const withSuspense = (element: React.ReactNode) => (
  <Suspense
    fallback={
      <p className="p-6 text-sm text-ink-2" role="status">
        Loading screen…
      </p>
    }
  >
    {element}
  </Suspense>
);

const router = createBrowserRouter([
  {
    path: "/",
    element: <App />,
    children: [
      { index: true, element: withSuspense(<Overview />) },
      { path: "routes", element: withSuspense(<RouteExplorer />) },
      { path: "heatmap", element: withSuspense(<SectorHeatmap />) },
      { path: "leadtime", element: withSuspense(<LeadTime />) },
      { path: "method", element: withSuspense(<MethodConsole />) },
      { path: "audit", element: withSuspense(<Audit />) },
    ],
  },
]);

const root = document.getElementById("root");
if (!root) {
  throw new Error("#root is missing from index.html");
}

ReactDOM.createRoot(root).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <RouterProvider router={router} />
      </ThemeProvider>
    </QueryClientProvider>
  </React.StrictMode>,
);
