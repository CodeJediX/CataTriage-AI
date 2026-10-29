package com.catatriage.doctor;

import android.content.*;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;
import java.io.*;

/** Only the explicitly granted, temporary camera file can be accessed. */
public class CaptureProvider extends ContentProvider {
  @Override
  public boolean onCreate() {
    return true;
  }

  private File file(Uri uri) throws FileNotFoundException {
    String name = uri.getLastPathSegment();
    if (name == null
        || !name.matches("capture-[a-f0-9-]{36}\\.jpg")
        || !("/" + name).equals(uri.getPath())) throw new FileNotFoundException();
    return new File(getContext().getCacheDir(), name);
  }

  @Override
  public ParcelFileDescriptor openFile(Uri uri, String mode) throws FileNotFoundException {
    return ParcelFileDescriptor.open(file(uri), ParcelFileDescriptor.parseMode(mode));
  }

  @Override
  public String getType(Uri uri) {
    return "image/jpeg";
  }

  @Override
  public Cursor query(Uri uri, String[] projection, String selection, String[] args, String order) {
    MatrixCursor result =
        new MatrixCursor(new String[] {OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE});
    try {
      result.addRow(new Object[] {"capture.jpg", file(uri).length()});
    } catch (Exception ignored) {
    }
    return result;
  }

  @Override
  public Uri insert(Uri u, ContentValues v) {
    throw new UnsupportedOperationException();
  }

  @Override
  public int update(Uri u, ContentValues v, String s, String[] a) {
    return 0;
  }

  @Override
  public int delete(Uri u, String s, String[] a) {
    return 0;
  }
}
