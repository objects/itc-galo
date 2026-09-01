# Evaluación de Prefactibilidad Inmobiliaria con IA en Bogotá

Este documento compila la conversación detallada sobre los requerimientos, normativas y arquitectura técnica necesarios para desarrollar una plataforma web B2B de prefactibilidad inmobiliaria asistida por Inteligencia Artificial en Bogotá, Colombia.

---

## 1. Pilares Esenciales de la Prefactibilidad Inmobiliaria
La evaluación de prefactibilidad determina si una idea de negocio es viable antes de realizar grandes inversiones de capital. Se divide en cuatro componentes críticos:

### A. Información Legal y Normativa
Establece qué se permite construir legalmente en el terreno.
* **Uso de suelo:** Certificados oficiales de los usos permitidos (residencial, comercial, industrial o mixto).
* **Potencial de edificación:** Altura máxima, número de pisos, densidad de viviendas y coeficientes de ocupación (COS/CUS).
* **Restricciones ambientales:** Afectaciones por áreas protegidas, cuerpos de agua, zonas de riesgo o patrimonio histórico.
* **Factibilidad de servicios:** Garantías de acceso a agua potable, alcantarillado, energía eléctrica y telecomunicaciones.

### B. Información de Mercado
Determina si existe demanda real para el producto inmobiliario propuesto.
* **Análisis de la oferta:** Inventario de competidores activos, precios por metro cuadrado, velocidades de venta y amenidades.
* **Análisis de la demanda:** Perfil socioeconómico del comprador ideal, preferencias de distribución y capacidad crediticia.
* **Absorción estimada:** Ritmo probable de ventas o rentas mensuales para proyectar los flujos de caja.

### C. Información Técnica y de Diseño
Define las características físicas y los desafíos constructivos del sitio.
* **Topografía y mecánica de suelos:** Estudios preliminares para prever costos de cimentación, excavación o contención.
* **Accesibilidad vial:** Conectividad con vías principales, transporte público y afectaciones de tráfico.
* **Anteproyecto arquitectónico:** Esquema básico con la distribución de áreas vendibles frente a áreas comunes (eficiencia).

### D. Información Financiera y Económica
Evalúa la rentabilidad estimada y los flujos de caja del negocio.
* **Estructura de costos:** Valor del terreno, costos de construcción por m², licencias, marketing y comisiones.
* **Estrategia de precios:** Precios proyectados de venta o renta basados en el estudio de mercado.
* **Indicadores de rentabilidad:** Cálculo preliminar de la Tasa Interna de Retorno (TIR), Valor Presente Neto (VPN) y margen de utilidad.
* **Fuentes de financiamiento:** Proporción de capital propio, preventas necesarias y crédito bancario requerido.

---

## 2. Contexto Específico: Bogotá, Colombia (POT Decreto 555 de 2021)
Al aplicar estos pilares a Bogotá, el marco normativo e institucional introduce variables geográficas y legales obligatorias:

* **Plan de Ordenamiento Territorial (POT) "Bogotá Reverdece":** Promueve una "ciudad multiusos" y de proximidad. Regula estrictamente las Áreas de Actividad y la mezcla de usos (comercial en primeros pisos, residencial arriba).
* **Áreas Mínimas de Vivienda:** El POT exige un área mínima de **36 m²** para las viviendas (incluyendo VIS). Esto redefine la densidad y cantidad de unidades maximizables por lote.
* **Cargas Urbanísticas y Cesiones:** Construir en altura o cambiar de densidad exige compensaciones al Distrito (entrega de espacio público, aceras o pagos monetarios).
* **Tratamientos Urbanísticos:** Clasificación del suelo en Desarrollo (lotes vacíos), Consolidación (barrios tradicionales) o Renovación Urbana (sectores estratégicos que otorgan mayor edificabilidad).
* **Infraestructura de Transporte:** La velocidad de absorción y valorización están ligadas a los grandes corredores de movilidad como la Línea 1 y 2 del Metro, la Avenida 68 y el Regiotram.
* **Mecánica de Suelos de la Sabana:** Los suelos planos del occidente y norte poseen arcillas blandas lacustres profundas. Esto hace obligatoria la cimentación mediante pilotes profundos, elevando sustancialmente los costos técnicos.
* **Modelo Financiero y de Preventas:** Mitigación obligatoria del riesgo mediante el uso de Sociedades Fiduciarias para el recaudo. El proyecto inicia obra solo al alcanzar el "Punto de Equilibrio" (60%-70% vendido).
* **Indexación en SMMLV:** Los proyectos de Vivienda de Interés Social (VIS) se fijan en Salarios Mínimos Mensuales Legales Vigentes al año de escrituración, requiriendo proyecciones precisas de inflación.

---

## 3. Arquitectura de la Aplicación Web B2B (IA + Python + Node.js + React)
Para automatizar este proceso y vender el software como un SaaS corporativo a constructoras y fondos de inversión, se estructuran cuatro motores computacionales y un flujo integrado de tecnologías:

### Componentes de Software:
* **Frontend (React):** Interfaz interactiva enfocada en la visualización geoespacial (utilizando Mapbox GL JS o React-Leaflet) para dibujar los polígonos de los lotes y pestañas con diagnósticos normativos y financieros.
* **Orquestador (Node.js):** Manejo del ciclo de vida de usuarios B2B, seguridad (JWT, roles), pasarelas de pago y WebSockets para actualizaciones en tiempo real sin congelar la pantalla.
* **Backend de Datos e IA (Python / FastAPI):** Procesamiento pesado que ejecuta algoritmos de RAG, cálculos geométricos, web scraping y simulaciones financieras.

### Motores de Información del MVP:

#### 1. Motor Normativo (RAG Semántico + Metadatos)
* **Ingesta de Datos:** Procesamiento del Decreto 555 de 2021 mediante pipelines de OCR avanzados (LayoutLM/Unstructured) para extraer tablas complejas en JSONs limpios.
* **Indexación Vectorial:** Almacenamiento de embeddings en **ChromaDB**.
* **Filtros de Precisión:** Uso de la Cédula Catastral como llave primaria y aplicación de filtros de metadatos (`where` en ChromaDB) por Localidad o UPL para evitar alucinaciones de la IA y limitar la búsqueda solo a las normas aplicables al lote.

#### 2. Motor de Mercado (Scraping + NLP)
* **Extracción de Datos:** Rastrear plataformas inmobiliarias en Colombia (Finca Raíz, Metrocuadrado, portales de constructoras).
* **Procesamiento (LLM / NLP):** Limpieza de texto no estructurado para tabular variables: precio por m², estrato (1 al 6), áreas privadas y amenidades.
* **Clasificación (Machine Learning):** Agrupación por clústeres para calcular de inmediato la oferta competidora y ritmos de absorción en la zona.

#### 3. Motor Técnico (GeoPandas + Algoritmos Generativos)
* **Cálculo Geométrico:** Conectores a la API de **Mapas Bogotá** e **IDECA** para extraer el polígono geométrico del lote. Uso de `GeoPandas` y `Shapely` en Python para restar afectaciones viales/ambientales y obtener el **Área Neta Urbanizable**.
* **Cabida Arquitectónica:** Algoritmo geométrico básico para calcular el área útil vendible total aplicando los índices de ocupación y construcción derivados del motor normativo.

#### 4. Motor Financiero (Funciones Puras de Python)
* **Automatización Matemática:** Multiplicación del área vendible por el precio por m² del mercado para proyectar ingresos totales.
* **Simulaciones de Riesgo:** Modelos de simulación (ej. Montecarlo) para estresar variables como incrementos del salario mínimo o retrasos en ventas.
* **Entregables Financieros:** Generación de flujos de caja y cálculo instantáneo de la Tasa Interna de Retorno (TIR), Valor Presente Neto (VPN) y Punto de Equilibrio.

---

### Flujo de Datos Técnico del Sistema:

```
[Usuario selecciona dirección/lote en React]
                     │
                     ▼
[Node.js recibe solicitud y autentica el token]
                     │
                     ▼
[FastAPI en Python calcula área con GeoPandas usando Mapas Bogotá]
                     │
                     ▼
[Filtro por metadatos en ChromaDB extrae la norma exacta del lote]
                     │
                     ▼
[Funciones de Python integran Costos, Precios de Scraping y generan la TIR/VPN]
                     │
                     ▼
[Node.js envía el JSON estructurado al Frontend de React para visualización]
```