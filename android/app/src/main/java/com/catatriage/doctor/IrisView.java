package com.catatriage.doctor;

import android.animation.ValueAnimator;
import android.content.Context;
import android.graphics.*;
import android.view.View;

/** A quiet optical scan motif, drawn locally without downloaded imagery. */
final class IrisView extends View {
  private final Paint p = new Paint(3);
  private float phase;
  private ValueAnimator motion;

  IrisView(Context context) {
    super(context);
    setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO);
  }

  @Override
  protected void onAttachedToWindow() {
    super.onAttachedToWindow();
    if (ValueAnimator.areAnimatorsEnabled()) {
      motion = ValueAnimator.ofFloat(0, 360);
      motion.setDuration(24000);
      motion.setRepeatCount(ValueAnimator.INFINITE);
      motion.addUpdateListener(
          a -> {
            phase = (float) a.getAnimatedValue();
            invalidate();
          });
      motion.start();
    }
  }

  @Override
  protected void onDetachedFromWindow() {
    if (motion != null) motion.cancel();
    super.onDetachedFromWindow();
  }

  @Override
  protected void onDraw(Canvas c) {
    super.onDraw(c);
    float x = getWidth() / 2f, y = getHeight() / 2f, r = Math.min(getWidth(), getHeight()) * .39f;
    p.setStyle(Paint.Style.STROKE);
    p.setStrokeWidth(1);
    p.setColor(Color.rgb(49, 86, 95));
    c.drawCircle(x, y, r * 1.14f, p);
    for (int i = 0; i < 72; i++) {
      double angle = Math.toRadians(i * 5 + phase * .1f);
      float a = r * (.52f + (i % 3) * .04f);
      p.setColor(i % 3 == 0 ? 0xff41d4cd : 0xff236875);
      p.setStrokeWidth(i % 3 == 0 ? 2 : 1);
      c.drawLine(
          x + (float) Math.cos(angle) * a,
          y + (float) Math.sin(angle) * a,
          x + (float) Math.cos(angle) * r,
          y + (float) Math.sin(angle) * r,
          p);
    }
    p.setColor(0xff60e8df);
    p.setStrokeWidth(2);
    c.drawArc(x - r, y - r, x + r, y + r, phase, 76, false, p);
    p.setStyle(Paint.Style.FILL);
    p.setColor(0xff0b2029);
    c.drawCircle(x, y, r * .43f, p);
    p.setColor(0xffb7f7ee);
    c.drawCircle(x + r * .15f, y - r * .18f, r * .09f, p);
    p.setColor(0xff467880);
    p.setStrokeWidth(1);
    c.drawLine(x - r * 1.3f, y, x - r * 1.05f, y, p);
    c.drawLine(x + r * 1.05f, y, x + r * 1.3f, y, p);
  }
}
