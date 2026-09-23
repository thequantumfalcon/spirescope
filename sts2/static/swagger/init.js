window.ui = SwaggerUIBundle({
  url: '/openapi.json', dom_id: '#swagger-ui', deepLinking: true,
  presets: [SwaggerUIBundle.presets.apis], layout: 'BaseLayout',
  validatorUrl: null, persistAuthorization: false
});
