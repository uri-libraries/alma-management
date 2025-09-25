<?xml version="1.0" encoding="UTF-8"?>
<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
  <xsl:output method="xml" indent="yes"/>
  <!-- Copy all elements and attributes unchanged -->
  <xsl:template match="@*|node()">
    <xsl:copy>
      <xsl:apply-templates select="@*|node()"/>
    </xsl:copy>
  </xsl:template>
  <!-- Replace phone_type 'alternative' with 'home' -->
  <xsl:template match="phone_types/phone_type[text()='alternative']">
    <phone_type desc="Home">home</phone_type>
  </xsl:template>
  <!-- Optional: Replace any invalid phone_type with 'home' -->
  <xsl:template match="phone_types/phone_type[not(.='home' or .='mobile' or .='work' or .='fax')]">
    <phone_type desc="Home">home</phone_type>
  </xsl:template>
</xsl:stylesheet>