/**
 * TanStack Query hooks, one per endpoint the screens consume.
 *
 * Query keys embed every parameter, so a changed control refetches and a repeated one
 * serves from cache. The method-preview POST is modelled as a query, not a mutation:
 * the server guarantees the same overrides produce the same preview, which is exactly
 * a query's caching contract.
 */

import { useQueries, useQuery } from "@tanstack/react-query";
import { api, unwrap } from "./client";
import type { MethodOverrides } from "./client";

export function useIndexSeries(series: string) {
  return useQuery({
    queryKey: ["index", series],
    queryFn: async () =>
      unwrap(await api.GET("/v1/index", { params: { query: { series, freq: "M" } } })),
  });
}

export function useVintage(series: string, period: string, asOf: string) {
  return useQuery({
    queryKey: ["vintage", series, period, asOf],
    queryFn: async () =>
      unwrap(
        await api.GET("/v1/index/vintage", {
          params: { query: { series, period, as_of: asOf } },
        }),
      ),
  });
}

export function useContributors(series: string, period: string) {
  return useQuery({
    queryKey: ["contributors", series, period],
    queryFn: async () =>
      unwrap(
        await api.GET("/v1/index/contributors", { params: { query: { series, period } } }),
      ),
  });
}

export function useRevisions(series?: string) {
  return useQuery({
    queryKey: ["revisions", series ?? "all"],
    queryFn: async () =>
      unwrap(
        await api.GET("/v1/index/revisions", {
          params: { query: series === undefined ? {} : { series } },
        }),
      ),
  });
}

export function useRoutes() {
  return useQuery({
    queryKey: ["routes"],
    queryFn: async () => unwrap(await api.GET("/v1/routes", {})),
  });
}

export function useRouteSeries(code: string, advanceDays?: number, carrier?: string) {
  return useQuery({
    queryKey: ["route-series", code, advanceDays ?? null, carrier ?? null],
    queryFn: async () =>
      unwrap(
        await api.GET("/v1/routes/{code}/series", {
          params: {
            path: { code },
            query: {
              ...(advanceDays === undefined ? {} : { advance_days: advanceDays }),
              ...(carrier === undefined ? {} : { carrier }),
            },
          },
        }),
      ),
  });
}

export interface RouteSeriesVariant {
  key: string;
  advanceDays?: number;
  carrier?: string;
}

/** One fare series per variant (advance window or carrier), fetched in parallel. */
export function useRouteSeriesBatch(code: string, variants: RouteSeriesVariant[]) {
  return useQueries({
    queries: variants.map((variant) => ({
      queryKey: [
        "route-series",
        code,
        variant.advanceDays ?? null,
        variant.carrier ?? null,
      ],
      queryFn: async () =>
        unwrap(
          await api.GET("/v1/routes/{code}/series", {
            params: {
              path: { code },
              query: {
                ...(variant.advanceDays === undefined ? {} : { advance_days: variant.advanceDays }),
                ...(variant.carrier === undefined ? {} : { carrier: variant.carrier }),
              },
            },
          }),
        ),
    })),
  });
}

export function useLeadtime(code: string, carrier?: string) {
  return useQuery({
    queryKey: ["leadtime", code, carrier ?? null],
    queryFn: async () =>
      unwrap(
        await api.GET("/v1/leadtime/{code}", {
          params: {
            path: { code },
            query: carrier === undefined ? {} : { carrier },
          },
        }),
      ),
  });
}

export function useHeatmap() {
  return useQuery({
    queryKey: ["heatmap"],
    queryFn: async () => unwrap(await api.GET("/v1/heatmap", {})),
  });
}

export function useCoverage(date: string) {
  return useQuery({
    queryKey: ["coverage", date],
    queryFn: async () =>
      unwrap(await api.GET("/v1/coverage", { params: { query: { date } } })),
  });
}

export function useBasket() {
  return useQuery({
    queryKey: ["basket"],
    queryFn: async () => unwrap(await api.GET("/v1/metadata/basket", {})),
  });
}

export function useMethod() {
  return useQuery({
    queryKey: ["method"],
    queryFn: async () => unwrap(await api.GET("/v1/metadata/method", {})),
  });
}

export function useCarriers() {
  return useQuery({
    queryKey: ["carriers"],
    queryFn: async () => unwrap(await api.GET("/v1/metadata/carriers", {})),
  });
}

export function useMethodPreview(overrides: MethodOverrides) {
  return useQuery({
    queryKey: ["method-preview", overrides],
    queryFn: async () =>
      unwrap(await api.POST("/v1/method/preview", { body: overrides })),
    placeholderData: (previous) => previous,
  });
}

export function useQuotes(route: string, period: string) {
  return useQuery({
    queryKey: ["quotes", route, period],
    enabled: route !== "",
    queryFn: async () =>
      unwrap(await api.GET("/v1/quotes", { params: { query: { route, period } } })),
  });
}

export function useProvenance(quoteId: string | null) {
  return useQuery({
    queryKey: ["provenance", quoteId],
    enabled: quoteId !== null,
    queryFn: async () =>
      unwrap(
        await api.GET("/v1/provenance/{quote_id}", {
          params: { path: { quote_id: quoteId ?? "" } },
        }),
      ),
  });
}
