import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { Suspense, lazy } from "react";
import ReactDOM from "react-dom/client";
import { RouterProvider, createBrowserRouter } from "react-router-dom";
import App from "./App";
import { ThemeProvider } from "./theme/ThemeContext";
import "./index.css";

// Lazy-loaded screen components
const Overview = lazy(() => import("./screens/Overview"));
const AirfareIndex = lazy(() => import("./screens/AirfareIndex"));
const RouteExplorer = lazy(() => import("./screens/RouteExplorer"));
const SectorHeatmap = lazy(() => import("./screens/SectorHeatmap"));
const LeadTime = lazy(() => import("./screens/LeadTime"));
const DataExplorerScreen = lazy(() => import("./screens/DataExplorerScreen"));
const ApiAccessScreen = lazy(() => import("./screens/ApiAccessScreen"));
const MethodConsole = lazy(() => import("./screens/MethodConsole"));
const Audit = lazy(() => import("./screens/Audit"));

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 60_000, retry: 1 } },
});

const withSuspense = (element: React.ReactNode) => (
  <Suspense
    fallback={
      <div className="flex h-64 items-center justify-center p-6 text-xs text-ink-2" role="status">
        Loading view…
      </div>
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
      { path: "airfare-index", element: withSuspense(<AirfareIndex />) },
      { path: "routes", element: withSuspense(<RouteExplorer />) },
      { path: "leadtime", element: withSuspense(<LeadTime />) },
      { path: "explorer", element: withSuspense(<DataExplorerScreen />) },
      { path: "api-access", element: withSuspense(<ApiAccessScreen />) },
      { path: "reports", element: withSuspense(<MethodConsole />) },
      { path: "settings", element: withSuspense(<Audit />) },
      // Legacy route aliases
      { path: "heatmap", element: withSuspense(<SectorHeatmap />) },
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
