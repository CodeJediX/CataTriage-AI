package com.catatriage.doctor;

import android.content.Context;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import org.json.*;

final class Api {
  static final String ROOT = BuildConfig.API_ORIGIN;
  private final Map<String, String> cookies = new LinkedHashMap<>();
  private final SessionVault vault;
  String csrf = "";

  static class Failure extends IOException {
    final int status;

    Failure(int status, String text) {
      super(text);
      this.status = status;
    }
  }

  Api(Context context) {
    vault = new SessionVault(context);
    try {
      JSONObject saved = new JSONObject(vault.load());
      Iterator<String> keys = saved.keys();
      while (keys.hasNext()) {
        String k = keys.next();
        cookies.put(k, saved.getString(k));
      }
    } catch (Exception ignored) {
    }
  }

  void clear() {
    cookies.clear();
    csrf = "";
    vault.clear();
  }

  static Map<String, String> form(String... values) {
    Map<String, String> result = new LinkedHashMap<>();
    for (int i = 0; i < values.length; i += 2) result.put(values[i], values[i + 1]);
    return result;
  }

  JSONObject get(String path) throws Exception {
    return json("GET", path, null, null);
  }

  JSONObject post(String path, Map<String, String> values) throws Exception {
    values = new LinkedHashMap<>(values);
    values.put("csrf", csrf);
    StringBuilder body = new StringBuilder();
    for (Map.Entry<String, String> e : values.entrySet()) {
      if (body.length() > 0) body.append('&');
      body.append(URLEncoder.encode(e.getKey(), "UTF-8"))
          .append('=')
          .append(URLEncoder.encode(e.getValue(), "UTF-8"));
    }
    return json(
        "POST",
        path,
        body.toString().getBytes(StandardCharsets.UTF_8),
        "application/x-www-form-urlencoded");
  }

  JSONObject json(String method, String path, byte[] body, String type) throws Exception {
    byte[] raw = request(method, path, body, type);
    try {
      return new JSONObject(new String(raw, StandardCharsets.UTF_8));
    } catch (JSONException e) {
      throw new IOException("The server returned an unexpected response. Try again shortly.");
    }
  }

  byte[] request(String method, String path, byte[] body, String type) throws Exception {
    if (!path.startsWith("/api/mobile/")) throw new IOException("Unsupported application request.");
    HttpURLConnection conn = (HttpURLConnection) new URL(ROOT + path).openConnection();
    conn.setConnectTimeout(30000);
    conn.setReadTimeout(300000);
    conn.setInstanceFollowRedirects(false);
    conn.setRequestMethod(method);
    conn.setRequestProperty("Accept", "application/json");
    conn.setRequestProperty("User-Agent", "CataTriage-Doctor-Android/1.0");
    conn.setRequestProperty("Cache-Control", "no-store");
    StringJoiner joined = new StringJoiner("; ");
    for (Map.Entry<String, String> c : cookies.entrySet())
      joined.add(c.getKey() + "=" + c.getValue());
    conn.setRequestProperty("Cookie", joined.toString());
    if (!csrf.isEmpty()) conn.setRequestProperty("X-CSRF-Token", csrf);
    try {
      if (body != null) {
        conn.setDoOutput(true);
        conn.setRequestProperty("Content-Type", type);
        conn.setFixedLengthStreamingMode(body.length);
        try (OutputStream out = conn.getOutputStream()) {
          out.write(body);
        }
      }
      int status = conn.getResponseCode();
      for (Map.Entry<String, List<String>> h : conn.getHeaderFields().entrySet())
        if ("Set-Cookie".equalsIgnoreCase(h.getKey())) {
          for (String val : h.getValue())
            for (HttpCookie cookie : HttpCookie.parse(val)) {
              if (cookie.getName().startsWith("catatriage_")) {
                if (cookie.getMaxAge() == 0) cookies.remove(cookie.getName());
                else cookies.put(cookie.getName(), cookie.getValue());
              }
            }
        }
      vault.save(new JSONObject(cookies).toString());
      InputStream input = status < 400 ? conn.getInputStream() : conn.getErrorStream();
      byte[] raw = input == null ? new byte[0] : read(input, 16 * 1024 * 1024);
      if (status < 200 || status >= 300) {
        String message = "Request failed (" + status + "). Try again.";
        try {
          JSONObject err = new JSONObject(new String(raw, StandardCharsets.UTF_8));
          if (err.opt("detail") instanceof JSONArray) {
            JSONObject issue = err.getJSONArray("detail").optJSONObject(0);
            message =
                issue == null
                    ? "Check the required form values."
                    : issue.optString("msg", "Check the required form values.");
          } else message = err.optString("error", err.optString("detail", message));
        } catch (Exception ignored) {
        }
        if (status == 401) clear();
        throw new Failure(status, message);
      }
      return raw;
    } finally {
      conn.disconnect();
    }
  }

  static byte[] read(InputStream input, int maximum) throws IOException {
    try (InputStream in = input;
        ByteArrayOutputStream out = new ByteArrayOutputStream()) {
      byte[] buf = new byte[16384];
      int n;
      while ((n = in.read(buf)) != -1) {
        if (out.size() + n > maximum) throw new IOException("The file is too large.");
        out.write(buf, 0, n);
      }
      return out.toByteArray();
    }
  }

  void bootstrap() throws Exception {
    csrf = get("/api/mobile/bootstrap").getString("csrf");
  }

  void upload(
      String caseId,
      String field,
      String name,
      byte[] bytes,
      java.util.function.Consumer<String> progress,
      List<String> ids)
      throws Exception {
    uploadFor("/api/mobile/intake", caseId, field, name, bytes, progress, ids);
  }

  void uploadFor(
      String action,
      String caseId,
      String field,
      String name,
      byte[] bytes,
      java.util.function.Consumer<String> progress,
      List<String> ids)
      throws Exception {
    JSONObject metadata =
        new JSONObject()
            .put("action", action)
            .put("target", caseId)
            .put("field", field)
            .put("name", name)
            .put("size", bytes.length);
    JSONObject prepared =
        json(
            "POST",
            "/api/mobile/uploads/prepare",
            metadata.toString().getBytes(StandardCharsets.UTF_8),
            "application/json");
    String id = prepared.getString("id");
    int chunk = prepared.getInt("chunk_size");
    for (int offset = 0, index = 0; offset < bytes.length; offset += chunk, index++) {
      progress.accept(
          "Uploading original image · "
              + Math.min(100, (offset + chunk) * 100 / bytes.length)
              + "%");
      request(
          "POST",
          "/api/mobile/uploads/" + id + "/chunks/" + index,
          Arrays.copyOfRange(bytes, offset, Math.min(bytes.length, offset + chunk)),
          "application/octet-stream");
    }
    ids.add(id);
  }
}
