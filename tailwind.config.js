/* Tailwind settings for the prebuilt static/css/tailwind.css.
   Rebuild after changing classes in a template:  python manage.py tailwind
   (or `python manage.py tailwind --watch` while working on templates). */
module.exports = {
  content: [
    "./templates/**/*.html",
    "./apps/**/templates/**/*.html",
    "./static/js/**/*.js",
  ],
  theme: { extend: {} },
  plugins: [],
};
