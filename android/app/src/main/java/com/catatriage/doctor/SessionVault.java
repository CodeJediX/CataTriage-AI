package com.catatriage.doctor;

import android.content.Context;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import java.security.KeyStore;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/** Device-bound encrypted session only; passwords and clinical records are not persisted. */
final class SessionVault {
  private final Context context;

  SessionVault(Context context) {
    this.context = context;
  }

  private SecretKey key() throws Exception {
    KeyStore ks = KeyStore.getInstance("AndroidKeyStore");
    ks.load(null);
    if (!ks.containsAlias("catatriage-session")) {
      KeyGenerator gen =
          KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
      gen.init(
          new KeyGenParameterSpec.Builder(
                  "catatriage-session",
                  KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
              .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
              .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
              .build());
      gen.generateKey();
    }
    return (SecretKey) ks.getKey("catatriage-session", null);
  }

  void save(String value) {
    try {
      Cipher c = Cipher.getInstance("AES/GCM/NoPadding");
      c.init(Cipher.ENCRYPT_MODE, key());
      String blob =
          Base64.encodeToString(c.getIV(), Base64.NO_WRAP)
              + ":"
              + Base64.encodeToString(
                  c.doFinal(value.getBytes(java.nio.charset.StandardCharsets.UTF_8)),
                  Base64.NO_WRAP);
      context.getSharedPreferences("private_session", 0).edit().putString("sealed", blob).apply();
    } catch (Exception e) {
      clear();
    }
  }

  String load() {
    try {
      String blob = context.getSharedPreferences("private_session", 0).getString("sealed", "");
      if (blob.isEmpty()) return "";
      String[] parts = blob.split(":");
      Cipher c = Cipher.getInstance("AES/GCM/NoPadding");
      c.init(
          Cipher.DECRYPT_MODE,
          key(),
          new GCMParameterSpec(128, Base64.decode(parts[0], Base64.NO_WRAP)));
      return new String(
          c.doFinal(Base64.decode(parts[1], Base64.NO_WRAP)),
          java.nio.charset.StandardCharsets.UTF_8);
    } catch (Exception e) {
      clear();
      return "";
    }
  }

  void clear() {
    context.getSharedPreferences("private_session", 0).edit().clear().apply();
  }
}
